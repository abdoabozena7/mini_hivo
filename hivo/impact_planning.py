"""Evidence-grounded impact planning for existing-project changes.

Stage 3 sits between the temporary Task Brain and execution planning.  The
module is deliberately model-agnostic: it defines bounded schemas, validates
weak-model proposals against Stage 1/2 IDs, applies one deterministic
reconciliation pass, and produces the immutable execution contract.  It never
reads or mutates subject-project files.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re


EXISTING_PROJECT = "EXISTING_PROJECT"

USER_STATED = "USER_STATED"
USER_CONFIRMED = "USER_CONFIRMED"
PROJECT_BRAIN = "PROJECT_BRAIN"
REPOSITORY_EVIDENCE = "REPOSITORY_EVIDENCE"
DERIVED_PLAN_DECISION = "DERIVED_PLAN_DECISION"

# Canonical Stage 3 identity is deliberately smaller than a repository
# ontology.  It is a task-scoped index over the semantic Stage 2 facts that
# are already accepted by the repository-evidence boundary.
CANONICAL_SURFACE_KINDS = (
    "OWNER", "INTERFACE", "PERSISTENCE", "TEST", "ENTRYPOINT", "OTHER",
)
CANONICAL_SURFACE_ROLES = (
    "INPUT_OWNER", "STATE_OWNER", "OWNER", "INTERFACE", "PERSISTENCE_OWNER",
    "RENDER_SURFACE", "CURRENT_TEST", "ENTRYPOINT", "REPOSITORY_SURFACE",
)
DISPOSITIONS = (
    "MUST_CHANGE", "INTERFACE_REUSE", "TEST_CHANGE", "PRESERVATION_ONLY",
    "VERIFY_ONLY", "INSUFFICIENT_EVIDENCE",
)
# V24.3 deliberately uses a separate, smaller model contract.  These values
# are not added to the legacy Impact Map disposition enum: the legacy map is
# still the downstream canonical artifact, while the choice object is only a
# bounded input to its deterministic compiler.
IMPACT_DECISION_CHOICES = (
    "MUST_CHANGE", "INTERFACE_REUSE", "TEST_CHANGE", "PRESERVATION_ONLY",
    "VERIFY_ONLY", "INSPECT_ONLY", "AUTHORITY_CHANGE",
)
IMPACT_DECISION_MODEL_FIELDS = (
    "slot_id", "decision", "chosen_target", "reason_code", "bounded_rationale",
)
IMPACT_DECISION_AUTHORITY_FIELDS = frozenset({
    "impact_id", "seed_id", "surface_id", "current_owner", "owner",
    "required_interfaces", "preservation_promises", "required_preservation_promises",
    "verification_contracts", "required_verification_contracts", "dnt",
    "prohibitions", "authority_refs", "evidence_refs", "path", "symbol",
    "symbols", "repository_evidence_ids", "requirement_ids", "scope_notes",
    "risk_notes", "mutation_target", "reuse_target", "provider_generation_identity",
    "candidate_obligation_ids", "surface_capabilities", "allowed_decisions",
    "decision_capabilities", "obligations_satisfied_by_decision",
    "inherited_obligation_ids", "obligation_assignments", "dnt_surface_ids",
    "prohibited_surface_ids", "allowed_targets", "authority_change_targets",
})
IMPACT_DECISION_FRAME_VERSION = "V24.4"
IMPACT_DECISION_FRAME_INCOMPLETE = "IMPACT_DECISION_FRAME_INCOMPLETE"
IMPACT_DECISION_OUTPUT_MALFORMED = "IMPACT_DECISION_OUTPUT_MALFORMED"
DUPLICATE_IMPACT_DECISION_SLOT = "DUPLICATE_IMPACT_DECISION_SLOT"
MISSING_IMPACT_DECISION_SLOT = "MISSING_IMPACT_DECISION_SLOT"
UNKNOWN_IMPACT_DECISION_SLOT = "UNKNOWN_IMPACT_DECISION_SLOT"
IMPACT_DECISION_NOT_ALLOWED = "IMPACT_DECISION_NOT_ALLOWED"
IMPACT_DECISION_TARGET_NOT_ALLOWED = "IMPACT_DECISION_TARGET_NOT_ALLOWED"
IMPACT_MAP_COMPILE_INVALID = "IMPACT_MAP_COMPILE_INVALID"
IMPACT_MAP_PARSE_INVALID = "IMPACT_MAP_PARSE_INVALID"
IMPACT_MAP_UNSUPPORTED_ENVELOPE = "IMPACT_MAP_UNSUPPORTED_ENVELOPE"
IMPACT_MAP_CANONICALIZATION_FAILED = "IMPACT_MAP_CANONICALIZATION_FAILED"
IMPACT_MAP_REQUIRED_SEMANTIC_FIELD_MISSING = "IMPACT_MAP_REQUIRED_SEMANTIC_FIELD_MISSING"
IMPACT_MAP_SEMANTIC_VALIDATION_FAILED = "IMPACT_MAP_SEMANTIC_VALIDATION_FAILED"
IMPACT_FRAME_COVERAGE_READY = "IMPACT_FRAME_COVERAGE_READY"
IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP = "IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP"
IMPACT_CHOICE_COVERAGE_READY = "IMPACT_CHOICE_COVERAGE_READY"
IMPACT_CHOICE_REQUIREMENT_GAP = "IMPACT_CHOICE_REQUIREMENT_GAP"
BEHAVIOR_CHANGE_UNCOVERED = "BEHAVIOR_CHANGE_UNCOVERED"
DOWNSTREAM_WEAK_IMPACT_CHOICE_COVERAGE_FAILURE = (
    "DOWNSTREAM_WEAK_IMPACT_CHOICE_COVERAGE_FAILURE"
)
EXCLUDED_IMPACT_DECISION_SLOT = "EXCLUDED_IMPACT_DECISION_SLOT"
IMPACT_DECISION_PROJECTION_INVALID = "IMPACT_DECISION_PROJECTION_INVALID"
IMPACT_DECISION_SLOT_CLASSIFICATIONS = (
    "MODEL_CHOICE_REQUIRED",
    "MODEL_CHOICE_SUPPORT",
    "DETERMINISTIC_INHERITED_ONLY",
    "EVIDENCE_ONLY",
)
DECISION_RELEVANT_IMPACT_CHOICE_PROJECTION_VERSION = "V24.4.3"
CHALLENGER_REVIEW_PROJECTION_VERSION = "V24.4.4"
CANONICAL_FINAL_PLAN_VERSION = 2
CANONICAL_FINAL_PLAN_REPRESENTATION = "CANONICAL_FINAL_PLAN"
CHALLENGER_REVIEW_PRIMARY = "CHALLENGER_REVIEW_PRIMARY"
CHALLENGER_REVIEW_SUPPORT = "CHALLENGER_REVIEW_SUPPORT"
DETERMINISTIC_FIXED_CONTEXT = "DETERMINISTIC_FIXED_CONTEXT"
EVIDENCE_ONLY = "EVIDENCE_ONLY"
CHALLENGER_REVIEW_SEMANTIC_UNITS = (
    "REQUIREMENT_GAP",
    "SCOPE",
    "AUTHORITY",
    "MINIMALITY",
    "DNT",
    "STALE_EVIDENCE",
    "VERIFICATION",
    "PRESERVATION",
    "CHALLENGE_TAXONOMY",
)
DECISION_CAPABILITY_NAMES = (
    "IMPLEMENTATION_CHANGE", "TEST_CHANGE", "INSPECTION_ONLY", "REUSE_ONLY",
    "PRESERVATION_ONLY", "AUTHORITY_CHANGE",
)
DECISION_CAPABILITY_TAXONOMY = {
    # Keep the existing choice/disposition names.  This is a capability
    # projection, not a new model-facing decision enum.
    "MUST_CHANGE": ("IMPLEMENTATION_CHANGE",),
    "INTERFACE_REUSE": ("REUSE_ONLY",),
    "TEST_CHANGE": ("TEST_CHANGE",),
    "PRESERVATION_ONLY": ("PRESERVATION_ONLY",),
    "VERIFY_ONLY": ("INSPECTION_ONLY",),
    "INSPECT_ONLY": ("INSPECTION_ONLY",),
    # Authority change is implementation-capable only after the existing
    # explicit-authority gate exposes this decision in a slot.
    "AUTHORITY_CHANGE": ("AUTHORITY_CHANGE", "IMPLEMENTATION_CHANGE"),
}
# Structured evidence relations used by the V24.4.2 binding boundary.  These
# are semantic identities, not filename or keyword matches.
STRUCTURED_SURFACE_RELATIONS = frozenset({
    "CURRENT_IMPLEMENTATION_SURFACE",
    "CURRENT_BEHAVIOR_OWNER",
    "CURRENT_RENDER_SURFACE",
    "CURRENT_INTERFACE_IMPLEMENTATION",
    "CURRENT_TEST",
    "CURRENT_STATE_OWNER",
    "TEST_TO_SOURCE_IMPORT",
    "PRESERVE_BEHAVIOR:ESCAPE_PAUSE_FLOW",
    "PRESERVE_BEHAVIOR:MOVEMENT_INPUT",
    "PRESERVE_OWNERSHIP:PAUSE_STATE_OWNER",
    "USER_FACING_PAUSE_INDICATOR",
})
NEW_SURFACE_PROPOSAL = "NEW_SURFACE_PROPOSAL"
MAX_CANONICAL_SURFACES = 32
MAX_SURFACE_EVIDENCE_IDS = 8
MAX_IMPACT_SEEDS = 32

IMPACT_KINDS = (
    "BEHAVIOR_CHANGE",
    "INTEGRATION_CHANGE",
    "TEST_CHANGE",
    "PRESERVATION_ONLY",
    "INTERFACE_REUSE",
    "CROSS_CUTTING_VERIFICATION",
)
NECESSITY_STATUSES = (
    "CANDIDATE", "MUST_CHANGE", "PRESERVATION_ONLY", "INSUFFICIENT_EVIDENCE",
)
COVERAGE_STATUSES = (
    "COVERED_BY_CHANGE",
    "COVERED_BY_PRESERVATION",
    "COVERED_BY_TEST",
    "CROSS_CUTTING",
    "UNASSIGNED",
)
REQUIREMENT_OBLIGATION_TYPES = (
    "BEHAVIOR_CHANGE",
    "ARCHITECTURE_REUSE",
    "PRESERVATION",
    "TEST",
    "PROHIBITION",
    "CROSS_CUTTING",
    "AUTHORITY_CHANGE",
)
OBLIGATION_COVERAGE_STATES = ("COVERED", "UNCOVERED")
CHALLENGE_LIFECYCLE_STATES = ("OPEN", "RESOLVED", "SUPERSEDED", "REJECTED")
CHALLENGE_APPLICABILITY_STATES = (
    "VALIDATED_APPLICABLE", "VALIDATED_NON_APPLICABLE", "REJECTED",
)
CHALLENGE_EFFECT_STATES = (
    "PENDING", "DEFERRED", "APPLIED", "SUPPRESSED", "NOT_APPLICABLE",
)
CHALLENGE_TYPES = (
    "UNSUPPORTED_NECESSITY",
    "WRONG_OWNER",
    "DUPLICATE_OWNERSHIP_RISK",
    "MISSING_IMPACT",
    "UNRELATED_CHANGE",
    "PRESERVATION_RISK",
    "INTERFACE_REUSE_MISSED",
    "TEST_GAP",
    "DEPENDENCY_GAP",
    "REQUIREMENT_GAP",
)
BLOCKING_CHALLENGE_TYPES = frozenset(CHALLENGE_TYPES)

MAX_IMPACT_ENTRIES = 12
MAX_PLAN_NODES = 8
MAX_EVIDENCE_REFS_PER_IMPACT = 6
MAX_REQUIREMENT_REFS_PER_IMPACT = 8
MAX_CHALLENGES = 12
MAX_PLAN_CHARS = 18000
MAX_PLANNER_CONTEXT_CHARS = 9000
MAX_CHALLENGER_CONTEXT_CHARS = 10000
MAX_REVISION_CONTEXT_CHARS = 10000
MAX_CHALLENGE_ROUNDS = 1
MAX_REVISION_ROUNDS = 1
MAX_TEXT_CHARS = 520

# Planning-role limits are hard model-facing character limits.  They apply to
# the complete string produced by the role renderer, including its fixed
# instructions, headings, separators, and canonical serialization.  The
# structured-output schema is sent through the provider's format transport,
# not appended after packet validation.  Keep these values separate from the larger
# structured-artifact bounds above: a complete artifact is not automatically a
# complete provider packet.
PLANNING_ROLE_LIMITS = {
    "ImpactPlanner": MAX_PLANNER_CONTEXT_CHARS,
    "ImpactChallenger": MAX_CHALLENGER_CONTEXT_CHARS,
    "ImpactPlanReviser": MAX_REVISION_CONTEXT_CHARS,
}

_CHANGE_RE = re.compile(
    r"\b(?:add|change|create|edit|extend|fix|implement|introduce|migrate|modify|remove|"
    r"replace|support|update)\b", re.IGNORECASE,
)
_PRESERVE_RE = re.compile(
    r"\b(?:do not change|keep|preserv(?:e|es|ed|ing)|remain|retain|unchanged|without breaking)\b",
    re.IGNORECASE,
)
_TEST_RE = re.compile(r"\b(?:assert|coverage|spec|test|tests|verification|verify)\b", re.IGNORECASE)
_REUSE_RE = re.compile(
    r"\b(?:reuse|use (?:the )?(?:current|existing)|keep using|existing (?:owner|interface|service|architecture)|"
    r"current (?:owner|interface|service|architecture))\b",
    re.IGNORECASE,
)
_PROHIBITION_RE = re.compile(
    r"\b(?:do not|don't|must not|never|no duplicate|no second (?:owner|service|state)|avoid(?:ing)? duplicate|"
    r"(?:without|instead of) (?:adding|creating|introducing|changing|breaking))\b",
    re.IGNORECASE,
)
_CROSS_CUTTING_RE = re.compile(
    r"\b(?:cross[- ]cutting|end[- ]to[- ]end|integration|across (?:the )?(?:project|system|application))\b",
    re.IGNORECASE,
)
_NEW_OWNER_RE = re.compile(
    r"\b(?:add|create|introduce|move)\b.{0,80}\b(?:field|flag|owner|state|store|controller)\b",
    re.IGNORECASE,
)
_NEW_INTERFACE_RE = re.compile(
    r"(?:\b(?:new|create|introduce|replace)\w*\b.{0,80}\b(?:api|controller|handler|interface|manager|service)\b|"
    r"\bnew[A-Za-z0-9_$]*(?:Controller|Handler|Manager|Service)\b)",
    re.IGNORECASE,
)
_PATH_RE = re.compile(r"(?:^|[\\/])[\w .-]+\.[A-Za-z0-9]+$|^[\w .-]+\.[A-Za-z0-9]+$")
_RAW_CONTEXT_KEYS = frozenset({
    "file_contents", "full_file_contents", "raw_repository", "repository_snapshot",
    "transcript", "messages", "conversation", "chain_of_thought", "reasoning", "support",
})
_SURFACE_ID_RE = re.compile(r"^SURF-[0-9]{3,}$", re.IGNORECASE)
_NEW_SURFACE_ID_RE = re.compile(r"^NEW-[A-Z0-9][A-Z0-9_.-]*$", re.IGNORECASE)
_IMPACT_ID_RE = re.compile(r"^IMPACT[-_](\d+)$", re.IGNORECASE)

# These are orchestration states, not model or repository identities.  They
# let the caller distinguish a bounded planning-packet failure from a bad
# model decision without adding another inference attempt.
IMPACT_PLANNING_CONTEXT_INCOMPLETE = "IMPACT_PLANNING_CONTEXT_INCOMPLETE"
IMPACT_CHALLENGER_CONTEXT_INCOMPLETE = "IMPACT_CHALLENGER_CONTEXT_INCOMPLETE"
IMPACT_PLAN_REVISION_CONTEXT_INCOMPLETE = "IMPACT_PLAN_REVISION_CONTEXT_INCOMPLETE"
PLANNING_PACKET_MANDATORY_OVERFLOW = "PLANNING_PACKET_MANDATORY_OVERFLOW"
PLANNING_PACKET_PROVIDER_OVERFLOW = "PLANNING_PACKET_PROVIDER_OVERFLOW"


def _compact_json(value):
    """Serialize a planning packet deterministically and without whitespace."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def planning_role_limit(role):
    """Return the frozen hard limit for a model-facing planning role."""
    name = str(role or "").strip()
    for known, limit in PLANNING_ROLE_LIMITS.items():
        if name.casefold() == known.casefold():
            return int(limit)
    return None


def _role_item_id(item, index):
    value = item if isinstance(item, dict) else {}
    return str(value.get("item_id") or value.get("id") or f"OPTIONAL-{index:03d}")


def _role_item_metadata(item, index):
    """Keep audit metadata while excluding executable/callback values."""
    value = item if isinstance(item, dict) else {"value": item}
    result = {
        "item_id": _role_item_id(value, index),
        "priority": int(value.get("priority", 0) or 0),
        "category": str(value.get("category") or "optional"),
    }
    for key in ("reason", "source_ids", "semantic_key", "path", "index"):
        if key not in value or callable(value.get(key)):
            continue
        raw = value.get(key)
        if isinstance(raw, tuple):
            raw = list(raw)
        result[key] = copy.deepcopy(raw)
    return result


def _role_payload_factory(mandatory_payload, selected_items):
    """Apply complete optional semantic units to a mandatory payload.

    An optional item is a list element or a complete field value.  There is no
    string-level truncation here: the smallest unit that can be removed is the
    semantic value supplied by the caller.
    """
    payload = copy.deepcopy(mandatory_payload if isinstance(mandatory_payload, dict) else {})

    def assign_path(path, value, index=None):
        if not path:
            return False
        cursor = payload
        for key in path[:-1]:
            if not isinstance(cursor, dict):
                return False
            if key not in cursor or not isinstance(cursor.get(key), (dict, list)):
                cursor[key] = {}
            cursor = cursor[key]
        key = path[-1]
        if isinstance(cursor, dict):
            existing = cursor.get(key)
            if isinstance(existing, list):
                position = index if index is not None else len(existing)
                position = max(0, min(int(position), len(existing)))
                existing.insert(position, copy.deepcopy(value))
            elif existing is None and index is not None:
                # A removed optional container is rebuilt as a list.  Do not
                # collapse the first selected semantic unit to a bare dict:
                # later units in the same field must remain independently
                # removable complete items.
                rebuilt = []
                position = max(0, min(int(index), len(rebuilt)))
                rebuilt.insert(position, copy.deepcopy(value))
                cursor[key] = rebuilt
            else:
                cursor[key] = copy.deepcopy(value)
            return True
        if isinstance(cursor, list):
            try:
                position = int(key)
            except (TypeError, ValueError):
                return False
            position = max(0, min(position, len(cursor)))
            cursor.insert(position, copy.deepcopy(value))
            return True
        return False

    for item in selected_items or []:
        value = item if isinstance(item, dict) else {"value": item}
        callback = value.get("apply")
        if callable(callback):
            callback(payload, copy.deepcopy(value.get("value")))
            continue
        path = value.get("path") or value.get("target_path")
        if isinstance(path, str):
            path = (path,)
        if not isinstance(path, (list, tuple)):
            field = value.get("field") or value.get("key")
            path = (field,) if field else ()
        if path:
            assign_path(tuple(path), value.get("value"), value.get("index"))
    return payload


def _role_packet_hash(material):
    encoded = _compact_json(material).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_planning_role_packet(
    role,
    mandatory_payload,
    optional_items=None,
    *,
    hard_limit=None,
    render=None,
    base_render=None,
    source_planning_context_hash=None,
    mandatory_items=None,
    payload_factory=None,
    packet_complete_override=None,
    planning_core_hash=None,
    mandatory_payload_audit=None,
    mandatory_semantic_coverage=None,
    mandatory_model_chars_before_normalization=None,
    mandatory_model_chars_after_normalization=None,
    mandatory_core_metrics=None,
):
    """Compile one exact, deterministic model-facing planning packet.

    The compiler first renders the mandatory projection, then greedily adds
    complete optional semantic units in descending priority order.  Every fit
    decision is made with the exact supplied renderer, so fixed role
    instructions and serialization separators are part of the same budget.
    ``payload_factory`` is useful when optional units affect more than one
    canonical field (for example a surface and its bound seed).
    """
    role = str(role or "PlanningRole")
    hard_limit = planning_role_limit(role) if hard_limit is None else int(hard_limit)
    hard_limit = max(1, int(hard_limit or 1))
    renderer = render if callable(render) else _compact_json
    base_renderer = base_render if callable(base_render) else renderer
    optional = []
    for index, item in enumerate(list(optional_items or []), 1):
        value = copy.deepcopy(item) if isinstance(item, dict) else {"value": item}
        value["item_id"] = _role_item_id(value, index)
        value["_order"] = index
        value["priority"] = int(value.get("priority", 0) or 0)
        optional.append(value)
    optional.sort(key=lambda item: (-item["priority"], item["_order"], item["item_id"]))

    factory = payload_factory or (
        lambda selected: _role_payload_factory(mandatory_payload, selected)
    )

    def make_payload(selected):
        value = factory(copy.deepcopy(list(selected or [])))
        return copy.deepcopy(value if isinstance(value, dict) else {})

    def render_exact(value):
        rendered = renderer(value)
        if not isinstance(rendered, str):
            rendered = str(rendered)
        return rendered

    def render_base(value):
        rendered = base_renderer(value)
        if not isinstance(rendered, str):
            rendered = str(rendered)
        return rendered

    mandatory_value = make_payload([])
    mandatory_serialized = _compact_json(mandatory_value)
    mandatory_rendered = render_exact(mandatory_value)
    # Renderers used by HIVO are envelope + canonical JSON.  Measuring the
    # difference against the exact mandatory serialization makes the static
    # role envelope and all headings/separators observable without guessing.
    envelope_chars = len(mandatory_rendered) - len(mandatory_serialized)
    mandatory_chars = len(mandatory_serialized)
    mandatory_ids = []
    for index, item in enumerate(list(mandatory_items or []), 1):
        mandatory_ids.append(
            str(item.get("item_id") or item.get("id") or f"MANDATORY-{index:03d}")
            if isinstance(item, dict) else str(item)
        )

    selected = []
    dropped = []
    mandatory_overflow = len(mandatory_rendered) > hard_limit
    if mandatory_overflow:
        dropped = [
            {
                **_role_item_metadata(item, item["_order"]),
                "reason": "MANDATORY_OVERFLOW",
            }
            for item in optional
        ]
    else:
        # Phase B/C/D: the mandatory render establishes the exact remaining
        # budget; optional units are then considered by stable priority.
        for item in optional:
            candidate_selected = selected + [item]
            candidate = make_payload(candidate_selected)
            candidate_rendered = render_exact(candidate)
            if len(candidate_rendered) <= hard_limit:
                selected.append(item)
            else:
                dropped.append({
                    **_role_item_metadata(item, item["_order"]),
                    "reason": "BUDGET",
                })

    payload = make_payload(selected)
    rendered = render_exact(payload)
    # Phase F is a final exact-render safety valve.  It only removes already
    # selected optional units and is normally a no-op because Phase D tested
    # each candidate with the same renderer.
    while len(rendered) > hard_limit and selected:
        remove = min(selected, key=lambda item: (item["priority"], -item["_order"], item["item_id"]))
        selected.remove(remove)
        dropped.append({
            **_role_item_metadata(remove, remove["_order"]),
            "reason": "FINAL_EXACT_RENDER",
        })
        payload = make_payload(selected)
        rendered = render_exact(payload)

    if mandatory_overflow:
        status = PLANNING_PACKET_MANDATORY_OVERFLOW
        errors = [
            f"mandatory {role} packet exceeds {hard_limit} rendered characters",
        ]
    elif len(rendered) > hard_limit:
        status = PLANNING_PACKET_PROVIDER_OVERFLOW
        errors = [f"exact {role} packet exceeds {hard_limit} rendered characters"]
    else:
        status = "READY"
        errors = []

    selected_ids = [_role_item_id(item, item["_order"]) for item in selected]
    dropped_ids = [str(item.get("item_id")) for item in dropped]
    serialized_chars = len(_compact_json(payload))
    separator_chars = len(rendered) - envelope_chars - serialized_chars
    base_rendered_packet = render_base(payload)
    base_mandatory_rendered = render_base(mandatory_value)
    mandatory_drops = []
    complete = (
        len(rendered) <= hard_limit
        and not mandatory_drops
        and not mandatory_overflow
    )
    if packet_complete_override is False:
        complete = False
        if status == "READY":
            status = "INCOMPLETE"
            errors = ["planning packet was marked incomplete by deterministic validation"]
    audit = {
        "role": role,
        "source_planning_context_hash": source_planning_context_hash,
        "hard_limit_chars": hard_limit,
        "mandatory_items": list(mandatory_ids),
        "mandatory_items_included": list(mandatory_ids),
        "mandatory_drops": list(mandatory_drops),
        "optional_items_considered": [
            _role_item_id(item, item["_order"]) for item in optional
        ],
        "optional_items_selected": selected_ids,
        "optional_items_dropped": dropped,
        "optional_items_dropped_ids": dropped_ids,
        "envelope_chars": envelope_chars,
        "mandatory_chars": mandatory_chars,
        "optional_chars": serialized_chars - mandatory_chars,
        "serialized_payload_chars": serialized_chars,
        "separator_chars": separator_chars,
        "rendered_chars": len(rendered),
        "remaining_chars": hard_limit - len(rendered),
        "mandatory_rendered_chars": len(mandatory_rendered),
        "base_rendered_chars": len(base_rendered_packet),
        "packet_complete": complete,
        "status": status,
        "errors": list(errors),
        "accounting": {
            "envelope_plus_payload_plus_separators": (
                envelope_chars + serialized_chars + separator_chars
            ),
            "rendered_chars": len(rendered),
            "matches_exact_render": (
                envelope_chars + serialized_chars + separator_chars == len(rendered)
            ),
        },
    }
    if planning_core_hash:
        audit["mandatory_core_hash"] = str(planning_core_hash)
    if mandatory_payload_audit is not None:
        audit["mandatory_payload_audit"] = copy.deepcopy(mandatory_payload_audit)
    if mandatory_semantic_coverage is not None:
        audit["mandatory_semantic_coverage"] = copy.deepcopy(mandatory_semantic_coverage)
        if isinstance(mandatory_semantic_coverage, list):
            audit["mandatory_semantic_coverage_rate"] = (
                sum(bool(
                    item.get("represented")
                    and item.get("source_provenance_retained")
                    and (
                        not item.get("model_semantic_required")
                        or item.get("model_semantic_represented")
                    )
                ) for item in mandatory_semantic_coverage if isinstance(item, dict))
                / len(mandatory_semantic_coverage)
                if mandatory_semantic_coverage else 1.0
            )
        else:
            audit["mandatory_semantic_coverage_rate"] = float(mandatory_semantic_coverage)
    if mandatory_model_chars_before_normalization is not None:
        audit["mandatory_model_chars_before_normalization"] = int(
            mandatory_model_chars_before_normalization
        )
    if mandatory_model_chars_after_normalization is not None:
        audit["mandatory_model_chars_after_normalization"] = int(
            mandatory_model_chars_after_normalization
        )
    if isinstance(mandatory_core_metrics, dict):
        audit["mandatory_core_metrics"] = copy.deepcopy(mandatory_core_metrics)
        for metric_name in (
            "mandatory_planning_records_input", "mandatory_semantic_units",
            "mandatory_semantic_units_deduplicated", "mandatory_provenance_refs",
            "planning_core_model_calls",
        ):
            if metric_name in mandatory_core_metrics:
                audit[metric_name] = copy.deepcopy(mandatory_core_metrics[metric_name])
    hash_material = {
        key: value for key, value in audit.items()
        if key not in {"errors", "status"}
    }
    hash_material["rendered_packet"] = rendered
    hash_material["payload"] = payload
    audit["packet_hash"] = _role_packet_hash(hash_material)
    # ``rendered_packet`` is the exact string later handed to the provider.
    # Callers must retain this value rather than reconstructing the prompt.
    audit["payload"] = copy.deepcopy(payload)
    audit["rendered_packet"] = rendered
    audit["exact_model_input"] = rendered
    audit["base_rendered_packet"] = base_rendered_packet
    audit["mandatory_rendered_packet"] = mandatory_rendered
    audit["mandatory_serialized_payload"] = mandatory_serialized
    audit["base_mandatory_rendered_chars"] = len(base_mandatory_rendered)
    return audit


compile_planning_role_packet = build_planning_role_packet


def _estimated_tokens(value):
    """Return a conservative character-based estimate for observability."""
    chars = len(value) if isinstance(value, str) else len(_compact_json(value))
    return (chars + 3) // 4


def _list_value(value):
    """Return bounded field values without iterating malformed strings.

    A scalar is treated as one value rather than as an iterable of characters;
    this lets optional interface tokens be rejected individually while keeping
    a malformed optional field from destroying the surrounding decision.
    """
    if isinstance(value, (list, tuple)):
        return list(value)
    if value is None or isinstance(value, (dict, set)):
        return []
    return [value]


def _candidate_impact_items(candidate):
    """Return the bounded raw decision items for observability accounting."""
    value = candidate if isinstance(candidate, dict) else {}
    if "impacts" in value:
        raw = value.get("impacts")
        return list(raw)[:MAX_IMPACT_ENTRIES] if isinstance(raw, (list, tuple)) else []
    return [value] if value.get("impact_id") else []


def _compact(value, limit=MAX_TEXT_CHARS):
    text = " ".join(str(value or "").split())
    limit = max(1, int(limit))
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _bounded_strings(values, count=8, chars=MAX_TEXT_CHARS):
    result = []
    for value in list(values or []):
        text = _compact(value, chars)
        if text and text not in result:
            result.append(text)
        if len(result) >= count:
            break
    return result


def _bounded_ids(values, count):
    return _bounded_strings(values, count, 80)


def _tokens(value):
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or "")).casefold()
    stop = {
        "add", "and", "change", "current", "existing", "for", "from", "into", "must",
        "project", "should", "task", "that", "the", "this", "through", "update", "using", "with",
    }
    result = set()
    for raw in re.findall(r"[a-z0-9_$.-]{3,}", normalized):
        item = raw.strip(".$-_")
        if item and item not in stop:
            result.add(item)
    return result


def _json_size(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def active_requirements(requirements):
    """Return non-deferred requirement records with stable IDs."""
    result = []
    for item in list(requirements or []):
        if not isinstance(item, dict):
            continue
        requirement_id = str(item.get("requirement_id", "")).strip()
        text = str(item.get("text", "")).strip()
        status = str(item.get("status", "active")).casefold()
        if not requirement_id or not text or status in {"deferred", "cancelled", "canceled"}:
            continue
        record = {
            "requirement_id": requirement_id,
            "text": _compact(text, 700),
            "provenance": str(item.get("provenance") or USER_STATED),
            "status": "active",
        }
        # Preserve only structured authority that later deterministic gates
        # can consume.  In particular, an atomic obligation ledger may carry
        # explicit surface bindings; free-form model rationale is never
        # admitted through this projection.
        for key in (
            "obligations", "obligation_types", "candidate_surface_ids",
            "authorized_surface_ids", "surface_ids", "surface_id",
            "candidate_surfaces", "authorized_surfaces", "candidate_slot_ids",
            "slot_ids", "target_surface_ids", "implementation_surface_ids",
            "authorized_implementation_surface_ids", "candidate_implementation_surface_ids",
            "inherited", "inherited_satisfaction", "authority_change",
            "authority_change_authorized", "allows_authority_change",
            "change_authority", "explicit_authority_change",
            "authorized", "explicit", "requested", "from", "to", "target",
            "target_owner", "new_owner", "object",
            "dnt", "prohibitions", "dnt_surface_ids", "prohibited_surface_ids",
            "forbidden_surface_ids", "do_not_touch_surface_ids", "do_not_modify_surface_ids",
        ):
            if key in item and item.get(key) not in (None, "", [], {}):
                record[key] = copy.deepcopy(item.get(key))
        result.append(record)
    return result


def _domain_tokens(value):
    """Return stable semantic tokens for requirement/surface relationships.

    Hyphenated source phrases are retained by ``_tokens`` for compatibility,
    while this projection also exposes their parts (``pause-state`` ->
    ``pause``, ``state``).  The projection is deliberately lexical and does
    not infer repository identities.
    """
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or "")).casefold()
    text = re.sub(r"[-_/]", " ", text)
    stop = {
        "add", "another", "behavior", "change", "current", "existing", "for",
        "from", "instead", "into", "must", "project", "relevant", "should",
        "support", "task", "that", "the", "this", "through", "update", "using",
        "with", "without",
    }
    result = set()
    for raw in re.findall(r"[a-z0-9_$]{3,}", text):
        if raw not in stop:
            result.add(raw)
        if raw.endswith("s") and len(raw) > 4 and raw[:-1] not in stop:
            result.add(raw[:-1])
    return result


def _obligation_slug(value, limit=42):
    text = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").upper()).strip("-")
    return (text or "REQ")[:limit].strip("-")


def _split_obligation_clauses(value):
    """Split only source-language conjunctions into atomic clauses."""
    text = _compact(value, 700).strip(" .")
    if not text:
        return []
    parts = re.split(
        r",\s*|\s+and\s+(?=(?:the\s+)?[A-Za-z])",
        text,
        flags=re.IGNORECASE,
    )
    result = []
    for part in parts:
        part = re.sub(
            r"^(?:and|while|the|current)\s+", "", part.strip(), flags=re.IGNORECASE,
        )
        if part and part not in result:
            result.append(part)
    return result or [text]


def _source_behavior_clauses(text):
    """Return behavior clauses from the user/source requirement only."""
    value = str(text or "").strip()

    def has_non_test_subject(clause):
        payload = _CHANGE_RE.sub(" ", str(clause or ""))
        payload = re.sub(r"\b(?:and|or|but|while)\b", " ", payload, flags=re.IGNORECASE)
        return bool(_domain_tokens(payload) - {
            "assert", "coverage", "focused", "integration", "spec", "test", "tests",
            "unit", "verification", "verify",
        })

    # Preservation tails are separate obligations.  This projection is
    # deterministic source parsing; it never examines model rationale.
    value = re.split(
        r"\bwhile\s+(?:preserv\w*|keep\w*|retain\w*)\b|"
        r"\b(?:and|but)\s+(?:preserv\w*|keep\w*|retain\w*)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" ,.;")
    # Keep independently requested mutations distinct when the source repeats
    # an action verb ("add X and update Y"), while excluding action words that
    # occur inside a negative DNT/prohibition clause.
    action_matches = list(_CHANGE_RE.finditer(value))
    negative_spans = [match.span() for match in re.finditer(
        r"\b(?:do not|don't|must not|never)\s+(?:\w+\s+){0,3}"
        r"(?:add|change|create|edit|extend|fix|implement|introduce|migrate|modify|"
        r"remove|replace|support|update)\b",
        value,
        re.IGNORECASE,
    )]
    positive_matches = [
        match for match in action_matches
        if not any(start <= match.start() < end for start, end in negative_spans)
    ]
    result = []
    for index, match in enumerate(positive_matches):
        end = positive_matches[index + 1].start() if index + 1 < len(positive_matches) else len(value)
        part = value[match.start():end]
        # A negative clause following a positive one is a separate
        # prohibition/preservation obligation, not part of the behavior
        # meaning assigned to the positive mutation.
        part = re.split(
            r"\s+(?:and|but|while)\s+(?=(?:do not|don't|must not|never)\b)",
            part,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        # A test clause is a separate TEST obligation, not product behavior.
        # Trim a trailing "and tests" from a preceding action and discard an
        # action whose only subject is the test boundary (for example,
        # "update tests").
        part = re.split(
            r"\s+(?:and|or|but|while)\s+(?=(?:(?:the|relevant|focused|unit|integration)\s+)*"
            r"(?:test|tests|spec|verification)\b)",
            part,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        part = re.sub(r"\s+(?:and|or|but|while)\s*$", "", part, flags=re.IGNORECASE)
        part = part.strip(" ,.;")
        if (
            part
            and _CHANGE_RE.search(part)
            and has_non_test_subject(part)
            and part not in result
        ):
            result.append(part)
    return result or ([value] if value else [])


def _source_preservation_clauses(text):
    value = str(text or "").strip()
    marker = re.search(
        r"\b(?:preserv\w*|keep\w*|retain\w*)\b", value, re.IGNORECASE,
    )
    if not marker:
        return []
    tail = value[marker.end():].strip(" ,.;:")
    tail = re.sub(r"^(?:the|current|existing)\s+", "", tail, flags=re.IGNORECASE)
    clauses = _split_obligation_clauses(tail)
    # Preserve a shared terminal noun in source coordination (for example,
    # "Escape and movement behavior") so each atomic record keeps the same
    # obligation meaning instead of reducing the first item to "Escape".
    if len(clauses) > 1:
        suffix_match = re.search(
            r"\b(behavio(?:u)?r)\s*\.?$", clauses[-1], re.IGNORECASE,
        )
        if suffix_match:
            suffix = suffix_match.group(1)
            for index, clause in enumerate(clauses[:-1]):
                normalized = re.sub(
                    r"^(?:preserv\w*|keep\w*|retain\w*)\s+",
                    "", clause.strip(), flags=re.IGNORECASE,
                )
                normalized = re.sub(
                    r"^(?:the|current|existing)\s+",
                    "", normalized, flags=re.IGNORECASE,
                )
                if len(re.findall(r"[A-Za-z0-9_$-]+", normalized)) == 1:
                    clauses[index] = f"{normalized.strip(' .')} {suffix}"
    result = []
    for clause in clauses:
        clause = re.sub(
            r"^(?:preserv\w*|keep\w*|retain\w*)\s+",
            "", clause.strip(), flags=re.IGNORECASE,
        )
        clause = re.sub(
            r"^(?:the|current|existing)\s+", "", clause, flags=re.IGNORECASE,
        )
        if clause.strip(" ."):
            result.append(_compact(f"Preserve {clause.strip(' .')}.", 520))
    return result


def _source_obligation_meaning(text, obligation_type):
    value = str(text or "").strip()
    if obligation_type == "BEHAVIOR_CHANGE":
        clauses = _source_behavior_clauses(value)
        return _compact(clauses[0] if clauses else value, 520)
    if obligation_type == "PRESERVATION":
        clauses = _source_preservation_clauses(value)
        return _compact(clauses[0] if clauses else value, 520)
    return _compact(value, 520)


def _obligation_id(requirement_id, obligation_type, ordinal):
    return "OBL-{}-{}-{:02d}".format(
        _obligation_slug(requirement_id),
        _obligation_slug(obligation_type, 28),
        int(ordinal),
    )


def _explicit_obligation_records(requirement, requirement_id, text):
    explicit = requirement.get("obligations")
    if not isinstance(explicit, list):
        return []
    result = []
    for ordinal, item in enumerate(explicit, 1):
        if not isinstance(item, dict):
            continue
        obligation_type = str(
            item.get("obligation_type") or item.get("type") or ""
        ).upper().strip()
        if obligation_type not in REQUIREMENT_OBLIGATION_TYPES:
            continue
        meaning = _compact(item.get("meaning") or item.get("text") or text, 520)
        if not meaning:
            continue
        value = {
            "obligation_id": str(item.get("obligation_id") or _obligation_id(
                requirement_id, obligation_type, ordinal,
            )),
            "requirement_id": requirement_id,
            "obligation_type": obligation_type,
            "meaning": meaning,
            "text": meaning,
            "source": "SOURCE_REQUIREMENT",
            "provenance": requirement.get("provenance", USER_STATED),
            "classification_provenance": DERIVED_PLAN_DECISION,
        }
        for key in (
            "candidate_surface_ids", "authorized_surface_ids", "surface_ids",
            "surface_id", "candidate_surfaces", "authorized_surfaces",
            "target_surface_ids", "implementation_surface_ids",
            "authorized_implementation_surface_ids", "candidate_implementation_surface_ids",
            "candidate_slot_ids", "slot_ids", "inherited", "inherited_satisfaction",
            "authority_change", "authority_change_authorized", "allows_authority_change",
            "change_authority", "explicit_authority_change", "authorized", "explicit",
            "requested", "from", "to", "target", "target_owner", "new_owner", "object",
            "dnt_surface_ids", "prohibited_surface_ids", "forbidden_surface_ids",
            "do_not_touch_surface_ids", "do_not_modify_surface_ids",
        ):
            if key in item and item.get(key) not in (None, "", [], {}):
                value[key] = copy.deepcopy(item.get(key))
            elif key in requirement and requirement.get(key) not in (None, "", [], {}):
                # Requirement-level structured bindings are inherited by an
                # explicit atomic record unless that record overrides them.
                # This keeps the source ledger authoritative without making
                # surface identity depend on prose.
                value[key] = copy.deepcopy(requirement.get(key))
        relations = _obligation_structured_relations(value)
        if relations:
            value["structured_relations"] = relations
        result.append(value)
    return result


def _atomic_obligations_for_requirement(requirement, requirement_types=None):
    """Build stable atomic obligations from one structured source record."""
    requirement = requirement if isinstance(requirement, dict) else {}
    requirement_id = str(requirement.get("requirement_id") or "").strip()
    text = _compact(requirement.get("text"), 700)
    explicit_types = [
        str(item).upper().strip() for item in list(
            requirement.get("obligation_types") or requirement_types or [],
        ) if str(item).upper().strip() in REQUIREMENT_OBLIGATION_TYPES
    ]
    explicit = _explicit_obligation_records(requirement, requirement_id, text)
    if explicit:
        behavior_values = [
            item for item in explicit if item.get("obligation_type") == "BEHAVIOR_CHANGE"
        ]
        if len(behavior_values) > 1:
            for item in behavior_values:
                if not any(item.get(key) not in (None, "", [], {}) for key in (
                    "candidate_surface_ids", "authorized_surface_ids", "surface_ids",
                    "candidate_slot_ids",
                )):
                    item["requires_explicit_surface_binding"] = True
        return explicit

    is_test = bool(_TEST_RE.search(text))
    is_preservation = bool(_PRESERVE_RE.search(text))
    is_reuse = bool(_REUSE_RE.search(text))
    is_prohibition = bool(_PROHIBITION_RE.search(text))
    # A test-only sentence is not a product behavior mutation merely because
    # it contains "add" or "update".  A compound sentence such as
    # "add export and tests" retains both obligations.
    change_clauses = re.split(r"\s+(?:and|or|;)\s+|,\s*", text, flags=re.IGNORECASE)
    def has_change_subject(clause):
        payload = _CHANGE_RE.sub(" ", str(clause or ""))
        payload = re.sub(r"\b(?:and|or|but|while)\b", " ", payload, flags=re.IGNORECASE)
        return bool(_domain_tokens(payload))

    non_test_change_clause = any(
        _CHANGE_RE.search(clause) and not _TEST_RE.search(clause)
        and has_change_subject(clause)
        for clause in change_clauses
    )
    behavior = bool(_CHANGE_RE.search(text)) and (
        not is_test or non_test_change_clause
    )
    # A negative instruction such as "do not modify the owner" is a
    # prohibition, not a request to mutate that surface.  Compound source
    # requirements still retain a behavior obligation when they contain an
    # independent positive change clause (for example, "add an indicator but
    # do not modify the owner").
    negative_action_spans = [match.span() for match in re.finditer(
        r"\b(?:do not|don't|must not|never)\s+(?:\w+\s+){0,3}"
        r"(?:add|change|create|edit|extend|fix|implement|introduce|migrate|modify|"
        r"remove|replace|support|update)\b",
        text,
        re.IGNORECASE,
    )]
    positive_change = any(
        not any(start <= match.start() < end for start, end in negative_action_spans)
        for match in _CHANGE_RE.finditer(text)
    )
    if negative_action_spans and not positive_change:
        behavior = False
    if is_prohibition and is_reuse and not re.search(
        r"\b(?:add|change|implement|modify|update|replace|remove)\b",
        text,
        re.IGNORECASE,
    ):
        behavior = False

    detected = []
    if behavior:
        detected.append("BEHAVIOR_CHANGE")
    if is_reuse:
        detected.append("ARCHITECTURE_REUSE")
    if is_preservation:
        detected.append("PRESERVATION")
    if is_test:
        detected.append("TEST")
    if is_prohibition:
        detected.append("PROHIBITION")
    if _CROSS_CUTTING_RE.search(text):
        detected.append("CROSS_CUTTING")
    types = explicit_types or [
        item for item in REQUIREMENT_OBLIGATION_TYPES if item in detected
    ]
    if not types:
        # An active declarative requirement still needs a concrete semantic
        # home. Treat it as behavior unless it was explicitly non-mutating.
        types = ["BEHAVIOR_CHANGE"]

    clauses_by_type = {}
    if "BEHAVIOR_CHANGE" in types:
        clauses_by_type["BEHAVIOR_CHANGE"] = _source_behavior_clauses(text)
    if "PRESERVATION" in types:
        clauses_by_type["PRESERVATION"] = _source_preservation_clauses(text)
    values = []
    for obligation_type in REQUIREMENT_OBLIGATION_TYPES:
        if obligation_type not in types:
            continue
        clauses = clauses_by_type.get(obligation_type) or [
            _source_obligation_meaning(text, obligation_type)
        ]
        for clause in clauses:
            value = {
                "obligation_id": _obligation_id(
                    requirement_id, obligation_type, len(values) + 1,
                ),
                "requirement_id": requirement_id,
                "obligation_type": obligation_type,
                "meaning": _compact(clause, 520),
                "text": _compact(clause, 520),
                "source": "SOURCE_REQUIREMENT",
                "provenance": requirement.get("provenance", USER_STATED),
                "classification_provenance": DERIVED_PLAN_DECISION,
            }
            for key in (
                "candidate_surface_ids", "authorized_surface_ids", "surface_ids",
                "surface_id", "candidate_surfaces", "authorized_surfaces",
                "target_surface_ids", "implementation_surface_ids",
                "authorized_implementation_surface_ids", "candidate_implementation_surface_ids",
                "candidate_slot_ids", "slot_ids", "inherited", "inherited_satisfaction",
                "authority_change", "authority_change_authorized", "allows_authority_change",
                "change_authority", "explicit_authority_change", "authorized", "explicit",
                "requested", "from", "to", "target", "target_owner", "new_owner", "object",
                "dnt_surface_ids", "prohibited_surface_ids", "forbidden_surface_ids",
                "do_not_touch_surface_ids", "do_not_modify_surface_ids",
            ):
                if requirement.get(key) not in (None, "", [], {}):
                    value[key] = copy.deepcopy(requirement.get(key))
            relations = _obligation_structured_relations(value)
            if relations:
                value["structured_relations"] = relations
            values.append(value)
    behavior_values = [
        item for item in values if item.get("obligation_type") == "BEHAVIOR_CHANGE"
    ]
    if len(behavior_values) > 1:
        # Distinct source behavior clauses cannot share every owner candidate
        # by lexical coincidence.  They must arrive with an explicit
        # structured surface/slot binding (or an equivalent future capability
        # proof) before one decision is allowed to cover more than one clause.
        for item in behavior_values:
            if not any(item.get(key) not in (None, "", [], {}) for key in (
                "candidate_surface_ids", "authorized_surface_ids", "surface_ids",
                "candidate_slot_ids",
            )):
                item["requires_explicit_surface_binding"] = True
    return values


def _atomic_obligation_records(ledger_or_requirements):
    """Return normalized atomic records without changing legacy type views."""
    records = _obligation_records(ledger_or_requirements)
    result = []
    for record in records:
        if not isinstance(record, dict):
            continue
        explicit = record.get("obligations")
        values = explicit if isinstance(explicit, list) and explicit else [
            *_atomic_obligations_for_requirement(record)
        ]
        for ordinal, item in enumerate(values, 1):
            if not isinstance(item, dict):
                continue
            value = copy.deepcopy(item)
            value.setdefault("requirement_id", record.get("requirement_id"))
            value.setdefault("obligation_type", "BEHAVIOR_CHANGE")
            value.setdefault("meaning", value.get("text") or record.get("text", ""))
            value.setdefault("text", value.get("meaning", ""))
            value.setdefault(
                "obligation_id",
                _obligation_id(
                    value.get("requirement_id"), value.get("obligation_type"), ordinal,
                ),
            )
            result.append(value)
    return result


def build_requirement_obligation_ledger(requirements):
    """Classify source requirements into deterministic atomic obligations."""
    raw = (
        requirements.get("requirements", [])
        if isinstance(requirements, dict) else list(requirements or [])
    )
    records = []
    for requirement in active_requirements(raw):
        obligation_values = _atomic_obligations_for_requirement(requirement)
        types = []
        for item in obligation_values:
            obligation_type = item.get("obligation_type")
            if obligation_type not in types:
                types.append(obligation_type)
        record = {
            "requirement_id": requirement["requirement_id"],
            "text": requirement["text"],
            "obligation_types": [
                item for item in REQUIREMENT_OBLIGATION_TYPES if item in types
            ],
            "obligations": obligation_values,
            "source_provenance": requirement.get("provenance", USER_STATED),
            "classification_provenance": DERIVED_PLAN_DECISION,
        }
        for key in (
            "candidate_surface_ids", "authorized_surface_ids", "surface_ids",
            "surface_id", "candidate_surfaces", "authorized_surfaces",
            "target_surface_ids", "implementation_surface_ids",
            "authorized_implementation_surface_ids", "candidate_implementation_surface_ids",
            "candidate_slot_ids", "slot_ids", "inherited", "inherited_satisfaction",
            "authority_change", "authority_change_authorized", "allows_authority_change",
            "change_authority", "explicit_authority_change", "authorized", "explicit",
            "requested", "from", "to", "target", "target_owner", "new_owner", "object",
            "dnt_surface_ids", "prohibited_surface_ids", "forbidden_surface_ids",
            "do_not_touch_surface_ids", "do_not_modify_surface_ids",
        ):
            if key in requirement and requirement.get(key) not in (None, "", [], {}):
                record[key] = copy.deepcopy(requirement.get(key))
        records.append(record)
    obligation_count = sum(len(item.get("obligations", [])) for item in records)
    return {
        "version": 2,
        "requirements": records,
        "obligation_count": obligation_count,
        "bounds": {
            "max_requirements": len(records),
            "max_obligations": obligation_count,
            "allowed_types": list(REQUIREMENT_OBLIGATION_TYPES),
        },
        "provenance": DERIVED_PLAN_DECISION,
    }


requirement_obligation_ledger = build_requirement_obligation_ledger


def _obligation_records(ledger_or_requirements):
    if isinstance(ledger_or_requirements, dict) and isinstance(
        ledger_or_requirements.get("requirements"), list
    ):
        return list(ledger_or_requirements.get("requirements", []))
    return build_requirement_obligation_ledger(ledger_or_requirements).get("requirements", [])


def compact_requirement_obligation_ledger(ledger_or_requirements):
    records = _obligation_records(ledger_or_requirements)
    compact_records = []
    for item in records:
        obligations = _atomic_obligations_for_requirement(item)
        compact_records.append({
            "requirement_id": item.get("requirement_id"),
            "obligation_types": list(dict.fromkeys(
                str(value.get("obligation_type")) for value in obligations
                if value.get("obligation_type")
            )) or list(item.get("obligation_types", [])),
            "obligations": [{
                key: copy.deepcopy(value.get(key))
                for key in (
                    "obligation_id", "obligation_type", "meaning", "text",
                    "candidate_surface_ids", "authorized_surface_ids",
                    "surface_ids", "surface_id", "candidate_surfaces",
                    "authorized_surfaces", "target_surface_ids",
                     "implementation_surface_ids", "authorized_implementation_surface_ids",
                     "candidate_implementation_surface_ids", "candidate_slot_ids", "slot_ids", "inherited",
                     "inherited_satisfaction", "requires_explicit_surface_binding",
                     "authority_change", "authority_change_authorized", "allows_authority_change",
                     "change_authority", "explicit_authority_change", "authorized", "explicit",
                     "requested", "from", "to", "target", "target_owner", "new_owner", "object",
                    "dnt_surface_ids", "prohibited_surface_ids", "forbidden_surface_ids",
                    "do_not_touch_surface_ids", "do_not_modify_surface_ids",
                    "structured_relations",
                    "source", "provenance",
                    "classification_provenance",
                ) if value.get(key) not in (None, "", [], {})
            } for value in obligations],
            "source_provenance": item.get("source_provenance", USER_STATED),
            "classification_provenance": DERIVED_PLAN_DECISION,
        })
    return {
        "version": 2,
        "requirements": compact_records,
        "obligation_count": sum(len(item.get("obligations", [])) for item in compact_records),
        "provenance": DERIVED_PLAN_DECISION,
    }


def _is_obligation_aware_artifact(artifact=None, ledger=None):
    """Identify an artifact that explicitly opts into the V24.4 contract."""
    value = artifact if isinstance(artifact, dict) else {}
    stored_ledger = value.get("requirement_obligation_ledger")
    if isinstance(stored_ledger, dict) and stored_ledger.get("version") == 2:
        return True
    if value.get("planning_mode") == "VERIFIED_STATE_REENTRY":
        return True
    if any(value.get(key) is not None for key in (
        "impact_decision_frame_hash", "impact_decision_frame_coverage",
        "impact_decision_choice_coverage", "source_planning_context_hash",
    )):
        return True
    return isinstance(ledger, dict) and ledger.get("version") == 2


def _legacy_requirement_obligation_ledger(ledger_or_requirements):
    """Return the full pre-V24.4 ledger used by legacy reconciliation code."""
    records = _obligation_records(ledger_or_requirements)
    legacy_types = [
        item for item in REQUIREMENT_OBLIGATION_TYPES
        if item != "AUTHORITY_CHANGE"
    ]
    legacy_records = []
    for item in records:
        obligation_types = list(item.get("obligation_types", []) or [])
        obligation_types = [
            item for item in legacy_types if item in obligation_types
        ]
        legacy_records.append({
            "requirement_id": item.get("requirement_id"),
            "text": item.get("text", ""),
            "obligation_types": obligation_types,
            "source_provenance": item.get("source_provenance", USER_STATED),
            "classification_provenance": DERIVED_PLAN_DECISION,
        })
    return {
        "version": 1,
        "requirements": legacy_records,
        "obligation_count": sum(
            len(item.get("obligation_types", [])) for item in legacy_records
        ),
        "bounds": {
            "max_requirements": len(legacy_records),
            "allowed_types": legacy_types,
        },
        "provenance": DERIVED_PLAN_DECISION,
    }


def _legacy_compact_requirement_obligation_ledger(ledger_or_requirements):
    """Project obligations into the pre-V24.4 type-level plan contract.

    V24.4 adds atomic obligation records to the verified-state planning
    artifact. Older Stage 3 callers still use the version-1 compact
    projection, whose canonical contract contains only requirement-level
    obligation types. This projection deliberately does not invent atoms; it
    only preserves the type information already present in the supplied
    ledger.
    """
    records = _legacy_requirement_obligation_ledger(ledger_or_requirements).get(
        "requirements", []
    )
    compact_records = []
    for item in records:
        obligation_types = list(item.get("obligation_types", []) or [])
        if not obligation_types:
            obligation_types = list(dict.fromkeys(
                str(value.get("obligation_type"))
                for value in list(item.get("obligations", []) or [])
                if isinstance(value, dict) and value.get("obligation_type")
            ))
        compact_records.append({
            "requirement_id": item.get("requirement_id"),
            "obligation_types": obligation_types,
            "source_provenance": item.get("source_provenance", USER_STATED),
            "classification_provenance": DERIVED_PLAN_DECISION,
        })
    return {
        "version": 1,
        "requirements": compact_records,
        "obligation_count": sum(
            len(item.get("obligation_types", [])) for item in compact_records
        ),
        "provenance": DERIVED_PLAN_DECISION,
    }


def _legacy_semantic_obligation_coverage(semantic):
    """Remove V24.4 atomic projections from a legacy plan projection."""
    value = semantic if isinstance(semantic, dict) else {}
    legacy = {
        key: copy.deepcopy(value.get(key))
        for key in (
            "requirements_covered", "requirements_uncovered",
            "behavior_obligations", "behavior_obligations_covered",
            "behavior_obligations_uncovered",
        )
        if key in value
    }
    legacy["requirements"] = []
    for record in list(value.get("requirements", []) or []):
        if not isinstance(record, dict):
            continue
        legacy["requirements"].append({
            key: copy.deepcopy(record.get(key))
            for key in (
                "requirement_id", "obligation_types", "obligations", "state", "provenance",
            )
            if key in record
        })
    return legacy


def bounded_evidence(evidence, max_items=12):
    """Keep semantic Stage 2 facts and hashes, never raw source support."""
    result = []
    for item in list(evidence or [])[:max_items]:
        if not isinstance(item, dict) or not item.get("evidence_id"):
            continue
        value = {
            "evidence_id": str(item.get("evidence_id")),
            "category": _compact(item.get("category"), 80),
            "fact": _compact(item.get("fact"), 300),
            "path": _compact(item.get("path"), 240),
            "symbol": _compact(item.get("symbol"), 180),
            "line_start": item.get("line_start"),
            "line_end": item.get("line_end"),
            "file_sha256": _compact(item.get("file_sha256"), 80),
            "provenance": REPOSITORY_EVIDENCE,
        }
        relations = item.get("structured_relations")
        if isinstance(relations, (list, tuple, set)):
            value["structured_relations"] = [
                str(relation) for relation in list(relations)[:8] if str(relation)
            ]
        elif isinstance(relations, str) and relations.strip():
            value["structured_relations"] = [relations.strip()]
        source_links = item.get("source_links")
        if isinstance(source_links, list) and source_links:
            value["source_links"] = copy.deepcopy(source_links[:8])
        if item.get("linked_from_paths"):
            value["linked_from_paths"] = _bounded_strings(
                item.get("linked_from_paths"), 8, 240,
            )
        if item.get("link_depth") is not None:
            value["link_depth"] = int(item.get("link_depth") or 0)
        result.append(value)
    return result


def _surface_symbol_base(symbol):
    """Return the owner symbol portion of a verified symbol."""
    text = str(symbol or "").strip()
    if not text:
        return ""
    return re.split(r"::|[.#:]", text, maxsplit=1)[0]


def _structured_relation_names(value):
    """Return only the bounded named relations carried by an evidence record."""
    if not isinstance(value, dict):
        return []
    pending = []
    for key in ("structured_relations", "structured_relation", "semantic_relations"):
        raw = value.get(key)
        if isinstance(raw, (list, tuple, set)):
            pending.extend(raw)
        elif isinstance(raw, str):
            pending.append(raw)
    result = []
    while pending:
        raw = pending.pop(0)
        if isinstance(raw, (list, tuple, set)):
            pending[0:0] = list(raw)
            continue
        if not isinstance(raw, str):
            continue
        name = raw.strip().upper()
        if name in STRUCTURED_SURFACE_RELATIONS and name not in result:
            result.append(name)
    return result[:8]


def _obligation_structured_relations(obligation):
    """Map known obligation meanings to explicit semantic identities.

    This is intentionally a small fail-closed vocabulary.  It does not
    select a path from prose; it only identifies the obligation concept that a
    structurally typed repository surface may satisfy.
    """
    value = obligation if isinstance(obligation, dict) else {}
    result = _structured_relation_names(value)
    meaning = str(value.get("meaning") or value.get("text") or "")
    normalized = " ".join(meaning.casefold().split())
    obligation_type = str(value.get("obligation_type") or "").upper()
    if obligation_type == "BEHAVIOR_CHANGE" and re.search(
        r"\bpause\s+indicator\b", normalized,
    ):
        result.append("USER_FACING_PAUSE_INDICATOR")
    if obligation_type == "PRESERVATION":
        if re.search(r"\bescape\b", normalized) and re.search(
            r"\b(?:pause|flow|behavior|behaviour)\b", normalized,
        ):
            result.append("PRESERVE_BEHAVIOR:ESCAPE_PAUSE_FLOW")
        if re.search(r"\bmovement\b", normalized) and re.search(
            r"\b(?:behavior|behaviour|input|controls?)\b", normalized,
        ):
            result.append("PRESERVE_BEHAVIOR:MOVEMENT_INPUT")
        if re.search(r"\bpausecontroller\b", normalized) and re.search(
            r"\b(?:owner|ownership|state)\b", normalized,
        ):
            result.append("PRESERVE_OWNERSHIP:PAUSE_STATE_OWNER")
    return list(dict.fromkeys(
        item for item in result if item in STRUCTURED_SURFACE_RELATIONS
    ))[:8]


def _surface_structured_relations(surface):
    return _structured_relation_names(surface if isinstance(surface, dict) else {})


def _surface_role(category, symbol="", fact="", structured_relations=None):
    category = str(category or "").upper()
    text = f"{symbol} {fact}".casefold()
    relations = set(
        item for item in (structured_relations or [])
        if str(item).upper() in STRUCTURED_SURFACE_RELATIONS
    )
    if category == "CURRENT_TEST":
        return "CURRENT_TEST"
    if "CURRENT_RENDER_SURFACE" in relations:
        return "RENDER_SURFACE"
    if category == "CURRENT_PERSISTENCE":
        return "PERSISTENCE_OWNER"
    if category == "CURRENT_INTERFACE":
        return "INTERFACE"
    if category == "CURRENT_ENTRYPOINT":
        return "ENTRYPOINT"
    if category in {"CURRENT_OWNER", "CURRENT_STATE_OWNER", "CURRENT_BEHAVIOR"}:
        if "input" in text or "keyboard" in text or "key state" in text:
            return "INPUT_OWNER"
        if "game" in text or "pause" in text or "state" in text:
            return "STATE_OWNER"
        return "OWNER"
    return "REPOSITORY_SURFACE"


def _surface_kind(category):
    category = str(category or "").upper()
    return {
        "CURRENT_OWNER": "OWNER",
        "CURRENT_STATE_OWNER": "OWNER",
        "CURRENT_BEHAVIOR": "OWNER",
        "CURRENT_INTERFACE": "INTERFACE",
        "CURRENT_PERSISTENCE": "PERSISTENCE",
        "CURRENT_TEST": "TEST",
        "CURRENT_ENTRYPOINT": "ENTRYPOINT",
    }.get(category, "OTHER")


def _surface_group_key(item, owner=False):
    path = str(item.get("path") or "").replace("\\", "/").strip()
    symbol = str(item.get("symbol") or "").strip()
    if owner:
        symbol = _surface_symbol_base(symbol)
    return path.casefold(), symbol.casefold()


def _surface_group_sort_key(group):
    role = group.get("role", "REPOSITORY_SURFACE")
    role_order = {
        "INPUT_OWNER": 0,
        "STATE_OWNER": 1,
        "RENDER_SURFACE": 2,
        "OWNER": 3,
        "INTERFACE": 4,
        "PERSISTENCE_OWNER": 5,
        "CURRENT_TEST": 6,
        "ENTRYPOINT": 7,
        "REPOSITORY_SURFACE": 8,
    }
    return (
        role_order.get(role, 9),
        str(group.get("path") or "").casefold(),
        str(group.get("symbol") or "").casefold(),
        str(group.get("first_evidence_id") or "").casefold(),
    )


def _group_structured_relations(records):
    result = []
    for record in records or []:
        for relation in _structured_relation_names(record):
            if relation not in result:
                result.append(relation)
    return result[:8]


def _group_source_links(records):
    result = []
    seen = set()
    for record in records or []:
        for link in list(record.get("source_links", []) or [])[:8]:
            if not isinstance(link, dict):
                continue
            identity = (
                str(link.get("path") or ""), str(link.get("module") or ""),
                int(link.get("line", 0) or 0), int(link.get("hop", 0) or 0),
            )
            if identity in seen:
                continue
            seen.add(identity)
            result.append(copy.deepcopy(link))
            if len(result) >= 8:
                return result
    return result


def canonical_surface_registry_schema():
    """Return the compact, model-facing canonical surface schema."""
    surface = {
        "type": "object",
        "properties": {
            "surface_id": {"type": "string"},
            "kind": {"type": "string", "enum": list(CANONICAL_SURFACE_KINDS)},
            "role": {"type": "string", "enum": list(CANONICAL_SURFACE_ROLES)},
            "path": {"type": "string"},
            "symbol": {"type": "string"},
            "verified_fact": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "structured_relations": {"type": "array", "items": {"type": "string"}},
            "source_links": {"type": "array", "items": {"type": "object"}},
            "owner_surface_id": {"type": ["string", "null"]},
        },
        "required": [
            "surface_id", "kind", "role", "path", "symbol", "verified_fact", "evidence_ids",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "version": {"type": "integer"},
            "surfaces": {"type": "array", "items": surface, "maxItems": MAX_CANONICAL_SURFACES},
            "bounds": {"type": "object"},
            "provenance": {"type": "string"},
        },
        "required": ["version", "surfaces", "bounds", "provenance"],
        "additionalProperties": False,
    }


def build_canonical_surface_registry(task_brain=None, evidence=None,
                                     max_surfaces=MAX_CANONICAL_SURFACES):
    """Derive authoritative existing-project identities from accepted evidence.

    The registry intentionally consumes only compact Stage 2 evidence.  Task
    Brain facts can make a role relevant, but cannot create a path or symbol
    that is absent from accepted evidence.
    """
    max_surfaces = min(MAX_CANONICAL_SURFACES, max(1, int(max_surfaces)))
    facts = bounded_evidence(evidence, max(MAX_CANONICAL_SURFACES * 2, 16))
    # Compatibility with Task Brain projections that carry accepted evidence
    # records inline.  Existing evidence remains authoritative and wins ties.
    seen_evidence = {str(item.get("evidence_id")) for item in facts}
    brain = task_brain if isinstance(task_brain, dict) else {}
    for field in ("current_owners", "current_interfaces", "current_state_ownership",
                  "relevant_tests", "relevant_dependencies"):
        for item in list(brain.get(field, []) or []):
            if not isinstance(item, dict) or not item.get("path"):
                continue
            evidence_ids = list(item.get("evidence_ids", []) or [])
            for evidence_id in evidence_ids:
                evidence_id = str(evidence_id)
                if evidence_id in seen_evidence:
                    continue
                facts.append({
                    "evidence_id": evidence_id,
                    "category": item.get("category", "CURRENT_BEHAVIOR"),
                    "fact": item.get("fact") or item.get("text", ""),
                    "path": item.get("path"), "symbol": item.get("symbol", ""),
                    "line_start": item.get("line_start"), "line_end": item.get("line_end"),
                    "file_sha256": item.get("file_sha256"),
                    "provenance": REPOSITORY_EVIDENCE,
                    "structured_relations": copy.deepcopy(item.get("structured_relations", [])),
                    "source_links": copy.deepcopy(item.get("source_links", [])),
                })
                seen_evidence.add(evidence_id)
                if len(facts) >= max(MAX_CANONICAL_SURFACES * 2, 16):
                    break
            if len(facts) >= max(MAX_CANONICAL_SURFACES * 2, 16):
                break
    groups = []
    owner_groups = {}
    interface_groups = {}
    simple_groups = {}
    for fact in facts:
        path = str(fact.get("path") or "").replace("\\", "/").strip()
        symbol = str(fact.get("symbol") or "").strip()
        category = str(fact.get("category") or "").upper()
        if not path:
            continue
        if category in {"CURRENT_OWNER", "CURRENT_STATE_OWNER", "CURRENT_BEHAVIOR"}:
            key = _surface_group_key(fact, owner=True)
            owner_groups.setdefault(key, []).append(fact)
        elif category == "CURRENT_INTERFACE":
            key = _surface_group_key(fact)
            interface_groups.setdefault(key, []).append(fact)
        elif category in {
            "CURRENT_PERSISTENCE", "CURRENT_TEST", "CURRENT_ENTRYPOINT",
        }:
            key = (_surface_kind(category),) + _surface_group_key(fact)
            simple_groups.setdefault(key, []).append(fact)
        else:
            # Preserve generic accepted repository roles without allowing
            # arbitrary model-created surfaces into the registry.
            key = (category,) + _surface_group_key(fact)
            simple_groups.setdefault(key, []).append(fact)

    for records in owner_groups.values():
        first = records[0]
        groups.append({
            "kind": "OWNER",
            "role": _surface_role(
                first.get("category"), first.get("symbol"), first.get("fact"),
                _group_structured_relations(records),
            ),
            "path": str(first.get("path") or "").replace("\\", "/"),
            "symbol": _surface_symbol_base(first.get("symbol")),
            "verified_fact": _compact(" ".join(item.get("fact", "") for item in records), 360),
            "evidence_ids": _bounded_ids(
                [item.get("evidence_id") for item in records], MAX_SURFACE_EVIDENCE_IDS,
            ),
            "first_evidence_id": records[0].get("evidence_id"),
            "structured_relations": _group_structured_relations(records),
            "source_links": _group_source_links(records),
        })
    for records in interface_groups.values():
        first = records[0]
        groups.append({
            "kind": "INTERFACE",
            "role": "INTERFACE",
            "path": str(first.get("path") or "").replace("\\", "/"),
            "symbol": str(first.get("symbol") or ""),
            "verified_fact": _compact(" ".join(item.get("fact", "") for item in records), 360),
            "evidence_ids": _bounded_ids(
                [item.get("evidence_id") for item in records], MAX_SURFACE_EVIDENCE_IDS,
            ),
            "first_evidence_id": records[0].get("evidence_id"),
            "structured_relations": _group_structured_relations(records),
            "source_links": _group_source_links(records),
        })
    for records in simple_groups.values():
        first = records[0]
        category = str(first.get("category") or "").upper()
        groups.append({
            "kind": _surface_kind(category),
            "role": _surface_role(
                category, first.get("symbol"), first.get("fact"),
                _group_structured_relations(records),
            ),
            "path": str(first.get("path") or "").replace("\\", "/"),
            "symbol": str(first.get("symbol") or ""),
            "verified_fact": _compact(" ".join(item.get("fact", "") for item in records), 360),
            "evidence_ids": _bounded_ids(
                [item.get("evidence_id") for item in records], MAX_SURFACE_EVIDENCE_IDS,
            ),
            "first_evidence_id": records[0].get("evidence_id"),
            "structured_relations": _group_structured_relations(records),
            "source_links": _group_source_links(records),
        })

    groups.sort(key=_surface_group_sort_key)
    groups = groups[:max_surfaces]
    surfaces = []
    for index, group in enumerate(groups, 1):
        value = {
            "surface_id": f"SURF-{index:03d}",
            "kind": group["kind"],
            "role": group["role"],
            "path": group["path"],
            "symbol": group["symbol"],
            "verified_path": group["path"],
            "verified_symbol": group["symbol"],
            "verified_fact": group["verified_fact"],
            "fact": group["verified_fact"],
            "evidence_ids": list(group["evidence_ids"]),
            "task_relevance_role": group["role"],
            "provenance": REPOSITORY_EVIDENCE,
            "structured_relations": list(group.get("structured_relations", []) or []),
            "source_links": copy.deepcopy(group.get("source_links", []))[:8],
        }
        surfaces.append(value)
    by_owner = {
        (str(item.get("path")).casefold(), str(item.get("symbol")).casefold()): item["surface_id"]
        for item in surfaces if item.get("kind") == "OWNER"
    }
    for item in surfaces:
        if item.get("kind") != "INTERFACE":
            continue
        owner_key = (
            str(item.get("path")).casefold(),
            _surface_symbol_base(item.get("symbol")).casefold(),
        )
        owner_id = by_owner.get(owner_key)
        if owner_id:
            item["owner_surface_id"] = owner_id
            item["owner_surface"] = owner_id
    registry = {
        "version": 1,
        "surfaces": surfaces,
        "surface_ids": [item["surface_id"] for item in surfaces],
        "evidence_ids": sorted({
            evidence_id for item in surfaces for evidence_id in item.get("evidence_ids", [])
        }),
        "bounds": {
            "max_surfaces": max_surfaces,
            "max_evidence_ids_per_surface": MAX_SURFACE_EVIDENCE_IDS,
        },
        "provenance": REPOSITORY_EVIDENCE,
    }
    return registry


canonical_impact_surface_registry = build_canonical_surface_registry
build_surface_registry = build_canonical_surface_registry


def canonical_surface_by_id(registry):
    value = registry if isinstance(registry, dict) else {}
    return {
        str(item.get("surface_id")): item
        for item in list(value.get("surfaces", []) or [])
        if isinstance(item, dict) and item.get("surface_id")
    }


def _task_brain_evidence_ids(task_brain):
    brain = task_brain if isinstance(task_brain, dict) else {}
    result = []
    for field in (
        "repository_evidence_ids", "current_owners", "current_interfaces",
        "current_state_ownership", "relevant_tests", "preservation_constraints",
        "relevant_dependencies", "acceptance_conditions",
    ):
        values = brain.get(field, [])
        if isinstance(values, (list, tuple, set)):
            for item in values:
                if isinstance(item, dict):
                    values_to_add = item.get("evidence_ids", [])
                else:
                    values_to_add = [item]
                result.extend(str(value) for value in list(values_to_add or []))
    return list(dict.fromkeys(result))


def normalize_impact_id(value):
    """Normalize only the bounded orchestration form of an impact ID.

    Impact IDs are local planner slots, so accepting harmless underscore and
    case variations is safe.  This function deliberately does not normalize
    paths, symbols, surface IDs, or repository evidence IDs.
    """
    text = str(value or "").strip()
    match = _IMPACT_ID_RE.fullmatch(text)
    if not match:
        return text
    return f"IMPACT-{int(match.group(1)):03d}"


def _task_brain_surface_signals(task_brain):
    """Collect deterministic identity signals already present in Task Brain."""
    brain = task_brain if isinstance(task_brain, dict) else {}
    fields = (
        "current_owners", "current_state_ownership", "current_interfaces",
        "relevant_tests", "preservation_constraints", "relevant_dependencies",
        "acceptance_conditions",
    )
    surface_ids = set()
    evidence_ids = set(_task_brain_evidence_ids(brain))
    paths = set()
    symbols = set()
    terms = set()
    for field in fields:
        for item in list(brain.get(field, []) or []):
            if not isinstance(item, dict):
                continue
            for key in ("surface_id", "canonical_surface_id"):
                if item.get(key):
                    surface_ids.add(str(item[key]))
            evidence_ids.update(str(value) for value in list(item.get("evidence_ids", []) or []))
            path = _normal_path(item.get("path"))
            if path:
                paths.add(path.casefold())
            symbol = str(item.get("symbol") or "").strip()
            if symbol:
                symbols.add(symbol.casefold())
            terms.update(_tokens(" ".join(
                str(item.get(key, "")) for key in ("text", "fact", "path", "symbol", "category")
            )))
    goal = brain.get("task_goal", "")
    if isinstance(goal, dict):
        goal = goal.get("text", "")
    terms.update(_tokens(goal))
    return {
        "surface_ids": surface_ids,
        "evidence_ids": evidence_ids,
        "paths": paths,
        "symbols": symbols,
        "terms": terms,
    }


def _requirement_surface_relations(requirements):
    result = {}
    ledger = build_requirement_obligation_ledger(requirements)
    for obligation in _atomic_obligation_records(ledger):
        requirement_id = str(obligation.get("requirement_id") or "")
        if not requirement_id:
            continue
        result.setdefault(requirement_id, set()).update(
            _obligation_structured_relations(obligation)
        )
    return result


def select_task_relevant_surfaces(task_brain, requirements, evidence, registry=None,
                                  max_surfaces=MAX_CANONICAL_SURFACES):
    """Select canonical surfaces before any packet serialization.

    Selection is driven only by Stage 1/2 material already available to the
    orchestrator.  Explicit Task Brain evidence and identity references are
    required signals; requirement/fact token overlap is a lower-priority
    relevance signal.  The returned order is always the registry's canonical
    order, so selection cannot renumber or otherwise mutate repository
    identity.
    """
    registry = registry or build_canonical_surface_registry(task_brain, evidence)
    surfaces = [
        item for item in list(registry.get("surfaces", []) or [])
        if isinstance(item, dict) and item.get("surface_id")
    ]
    max_surfaces = min(MAX_CANONICAL_SURFACES, max(1, int(max_surfaces)))
    signals = _task_brain_surface_signals(task_brain)
    reqs = active_requirements(requirements)
    goal = (task_brain or {}).get("task_goal", "") if isinstance(task_brain, dict) else ""
    if isinstance(goal, dict):
        goal = goal.get("text", "")
    goal_terms = _tokens(goal)
    requirement_relations = _requirement_surface_relations(reqs)
    all_requirement_relations = set().union(*requirement_relations.values()) if requirement_relations else set()
    scored = []
    for index, surface in enumerate(surfaces):
        surface_id = str(surface.get("surface_id"))
        surface_evidence = {str(item) for item in surface.get("evidence_ids", []) or []}
        path = _normal_path(surface.get("path"))
        symbol = str(surface.get("symbol") or "").strip()
        surface_terms = _tokens(" ".join([
            str(surface.get("verified_fact", "")), symbol, str(surface.get("role", "")),
            str(surface.get("kind", "")), path,
        ]))
        surface_relations = set(_surface_structured_relations(surface))
        score = 0
        required = False
        reasons = []
        if surface_id in signals["surface_ids"]:
            score += 10000
            required = True
            reasons.append("task_brain_surface_id")
        evidence_overlap = surface_evidence.intersection(signals["evidence_ids"])
        if evidence_overlap:
            score += 4000 + min(300, len(evidence_overlap) * 50)
            required = True
            reasons.append("task_brain_evidence")
        if path.casefold() in signals["paths"]:
            score += 2500
            required = True
            reasons.append("task_brain_path")
        if symbol and symbol.casefold() in signals["symbols"]:
            score += 2500
            required = True
            reasons.append("task_brain_symbol")
        relation_overlap = surface_relations.intersection(all_requirement_relations)
        if relation_overlap:
            score += 6000 + min(400, len(relation_overlap) * 100)
            required = True
            reasons.append("structured_requirement_relation")
        requirement_overlap = 0
        for requirement in reqs:
            requirement_overlap = max(
                requirement_overlap,
                len(_tokens(requirement.get("text")) & surface_terms),
            )
        if requirement_overlap:
            score += 100 + requirement_overlap * 10
            reasons.append("requirement_overlap")
        goal_overlap = len(goal_terms & surface_terms)
        if goal_overlap:
            score += goal_overlap * 5
            reasons.append("task_goal_overlap")
        scored.append({
            "index": index, "surface": surface, "score": score, "required": required,
            "reasons": reasons,
        })

    explicit = [item for item in scored if item["required"]]
    relevant = [item for item in scored if item["score"] > 0]
    if not relevant:
        # An existing-project registry with no direct Task Brain signal is
        # still safer when retained in full up to the deterministic registry
        # bound; there is no model inference involved in this fallback.
        relevant = list(scored)
    ranked = sorted(relevant, key=lambda item: (-item["score"], item["index"]))
    chosen = ranked[:max_surfaces]
    chosen_ids = {str(item["surface"].get("surface_id")) for item in chosen}
    required_ids = {
        str(item["surface"].get("surface_id")) for item in explicit
    }
    by_surface_id = {
        str(item.get("surface_id")): item for item in surfaces
    }
    # An interface without its verified owner is not a complete planning
    # choice.  Add owner dependencies before serialization when the bound
    # allows it; otherwise the packet builder reports a controlled omission.
    dependency_ids = {
        str(item.get("surface", {}).get("owner_surface_id"))
        for item in chosen
        if item.get("surface", {}).get("owner_surface_id")
    }
    required_ids.update(dependency_ids)
    for dependency_id in sorted(dependency_ids):
        if dependency_id in chosen_ids or len(chosen_ids) >= max_surfaces:
            continue
        if dependency_id in by_surface_id:
            chosen_ids.add(dependency_id)
    missing_required = sorted(required_ids - chosen_ids)
    # Never silently replace a required identity with a lower-scoring one.
    # The packet builder will turn this into a controlled incomplete state.
    selected = [item for item in surfaces if str(item.get("surface_id")) in chosen_ids]
    dropped = [
        str(item.get("surface_id")) for item in surfaces
        if str(item.get("surface_id")) not in chosen_ids
    ]
    return {
        "selected": selected,
        "selected_surface_ids": [str(item.get("surface_id")) for item in selected],
        "dropped_surface_ids": dropped,
        "required_surface_ids": sorted(required_ids),
        "missing_required_surface_ids": missing_required,
        "scores": {
            str(item["surface"].get("surface_id")): {
                "score": item["score"], "required": item["required"],
                "reasons": list(item["reasons"]),
            }
            for item in scored
        },
        "registry_surface_ids": [str(item.get("surface_id")) for item in surfaces],
    }


def build_impact_seeds(task_brain, requirements, evidence, registry=None,
                       selected_surface_ids=None):
    """Create deterministic, non-authoritative impact slots from verified facts."""
    registry = registry or build_canonical_surface_registry(task_brain, evidence)
    selected = None
    if selected_surface_ids is not None:
        selected = {str(item) for item in list(selected_surface_ids or [])}
    brain_ids = set(_task_brain_evidence_ids(task_brain))
    reqs = active_requirements(requirements)
    requirement_relations = _requirement_surface_relations(reqs)
    seeds = []
    for registry_index, surface in enumerate(list(registry.get("surfaces", []) or []), 1):
        if selected is not None and str(surface.get("surface_id")) not in selected:
            continue
        if len(seeds) >= MAX_IMPACT_SEEDS:
            break
        evidence_ids = list(surface.get("evidence_ids", []) or [])
        relevant = bool(brain_ids.intersection(evidence_ids)) if brain_ids else True
        terms = _tokens(
            " ".join([surface.get("verified_fact", ""), surface.get("symbol", ""), surface.get("role", "")])
        )
        surface_relations = set(_surface_structured_relations(surface))
        req_ids = []
        for requirement in reqs:
            requirement_id = str(requirement["requirement_id"])
            relation_match = surface_relations.intersection(
                requirement_relations.get(requirement_id, set())
            )
            if relation_match or terms.intersection(_tokens(requirement.get("text"))):
                req_ids.append(requirement["requirement_id"])
        seeds.append({
            # Keep slot identity stable when relevance selection omits an
            # earlier registry surface; IMPACT-005 remains the slot for the
            # fifth canonical surface in every packet.
            "seed_id": f"SEED-{registry_index:03d}",
            "impact_id": f"IMPACT-{registry_index:03d}",
            "surface_id": surface.get("surface_id"),
            "kind": surface.get("kind"),
            "role": surface.get("task_relevance_role") or surface.get("role"),
            "requirement_ids": _bounded_ids(req_ids, MAX_REQUIREMENT_REFS_PER_IMPACT),
            "evidence_ids": _bounded_ids(evidence_ids, MAX_SURFACE_EVIDENCE_IDS),
            "eligible": relevant,
            "verified_path": surface.get("path"),
            "verified_symbol": surface.get("symbol"),
            "verified_fact": surface.get("verified_fact"),
            "canonical_path": surface.get("path"),
            "canonical_symbol": surface.get("symbol"),
            "canonical_evidence_ids": _bounded_ids(evidence_ids, MAX_SURFACE_EVIDENCE_IDS),
            "owner_surface_id": surface.get("owner_surface_id"),
            "surface_kind": surface.get("kind"),
            "surface_role": surface.get("role"),
            "structured_relations": list(surface_relations),
            "provenance": REPOSITORY_EVIDENCE,
        })
    # A behavior requirement and an architecture-reuse requirement may be
    # two clauses of one responsibility.  If they share domain language, an
    # existing OWNER already anchored by the reuse clause receives the
    # behavior hint as a companion relationship.  This changes hints only;
    # canonical identity and mutation authority remain untouched.
    obligation_by_id = {
        item["requirement_id"]: item
        for item in _obligation_records(build_requirement_obligation_ledger(reqs))
    }
    req_by_id = {item["requirement_id"]: item for item in reqs}
    companion_pairs = []
    for behavior_id, behavior in obligation_by_id.items():
        if "BEHAVIOR_CHANGE" not in behavior.get("obligation_types", []):
            continue
        for reuse_id, reuse in obligation_by_id.items():
            if behavior_id == reuse_id or "ARCHITECTURE_REUSE" not in reuse.get("obligation_types", []):
                continue
            shared = sorted(
                _domain_tokens(req_by_id[behavior_id]["text"])
                & _domain_tokens(req_by_id[reuse_id]["text"])
            )
            if shared:
                companion_pairs.append((behavior_id, reuse_id, shared[:4]))
    for seed in seeds:
        relationships = []
        original_ids = list(seed.get("requirement_ids", []))
        for behavior_id, reuse_id, shared in companion_pairs:
            if reuse_id not in original_ids or behavior_id in seed.get("requirement_ids", []):
                continue
            if seed.get("surface_kind") != "OWNER":
                continue
            seed["requirement_ids"] = _bounded_ids(
                list(seed.get("requirement_ids", [])) + [behavior_id],
                MAX_REQUIREMENT_REFS_PER_IMPACT,
            )
            relationships.append({
                "requirement_id": behavior_id,
                "companion_requirement_id": reuse_id,
                "relationship": "BEHAVIOR_REUSE_COMPANION",
                "shared_terms": shared,
                "provenance": DERIVED_PLAN_DECISION,
            })
        seed["requirement_relationships"] = relationships[:4]
    return seeds


canonical_impact_seeds = build_impact_seeds
surface_bound_impact_seeds = build_impact_seeds


def validate_impact_seeds(seeds, registry, selected_surface_ids=None):
    """Validate that every deterministic seed is bound to a known surface."""
    by_id = canonical_surface_by_id(registry)
    selected = {str(item) for item in list(selected_surface_ids or [])}
    errors = []
    seen = set()
    normalized = []
    for seed in list(seeds or [])[:MAX_IMPACT_SEEDS]:
        if not isinstance(seed, dict):
            errors.append("impact seed must be an object")
            continue
        impact_id = normalize_impact_id(seed.get("impact_id"))
        surface_id = str(seed.get("surface_id") or "")
        if not _IMPACT_ID_RE.fullmatch(impact_id) or impact_id in seen:
            errors.append(f"{impact_id or '<missing>'}: invalid or duplicate impact seed ID")
        seen.add(impact_id)
        surface = by_id.get(surface_id)
        if not surface:
            errors.append(f"{impact_id}: unknown canonical surface binding")
            continue
        if selected and surface_id not in selected:
            errors.append(f"{impact_id}: seed surface is outside selected packet surfaces")
        if _normal_path(seed.get("canonical_path", seed.get("verified_path"))) != _normal_path(surface.get("path")):
            errors.append(f"{impact_id}: seed path is not canonical")
        if str(seed.get("canonical_symbol", seed.get("verified_symbol", ""))) != str(surface.get("symbol", "")):
            errors.append(f"{impact_id}: seed symbol is not canonical")
        if set(str(item) for item in seed.get("canonical_evidence_ids", seed.get("evidence_ids", [])) or []) != set(
            str(item) for item in surface.get("evidence_ids", []) or []
        ):
            errors.append(f"{impact_id}: seed evidence is not canonical")
        if seed.get("owner_surface_id") not in {None, surface.get("owner_surface_id")}:
            errors.append(f"{impact_id}: seed owner relation is not canonical")
        normalized.append({**copy.deepcopy(seed), "impact_id": impact_id})
    expected = [item.get("impact_id") for item in normalized]
    return {
        "valid": not errors,
        "errors": errors[:24],
        "seeds": normalized,
        "impact_ids": [item.get("impact_id") for item in normalized],
        "surface_ids": [item.get("surface_id") for item in normalized],
        "expected_impact_ids": expected,
        "seed_count": len(normalized),
    }


def _task_brain_slice(task_brain):
    brain = task_brain if isinstance(task_brain, dict) else {}
    result = {
        "task_id": _compact(brain.get("task_id"), 100),
        "task_goal": copy.deepcopy(brain.get("task_goal", {})),
        "project_mode": brain.get("project_mode"),
        "source_requirement_ids": _bounded_ids(brain.get("source_requirement_ids"), 24),
    }
    caps = {
        "user_confirmed_decisions": 4,
        "relevant_project_brain_projection": 6,
        "current_owners": 6,
        "current_interfaces": 6,
        "current_state_ownership": 6,
        "relevant_dependencies": 4,
        "relevant_tests": 6,
        "preservation_constraints": 6,
        "acceptance_conditions": 6,
        "known_non_goals": 3,
    }
    for field, cap in caps.items():
        values = []
        for item in list(brain.get(field, []) or [])[:cap]:
            if not isinstance(item, dict):
                continue
            values.append({
                key: copy.deepcopy(value)
                for key, value in item.items()
                if key in {
                    "text", "provenance", "requirement_ids", "evidence_ids", "path", "symbol",
                    "category", "decision_id", "project_brain_field",
                }
            })
        result[field] = values
    return result


def _trim_context(context, max_chars):
    context = copy.deepcopy(context)
    trim_fields = (
        "project_invariants", "accepted_repository_evidence", "preservation_constraints",
        "current_interfaces", "current_state_ownership", "current_owners", "relevant_tests",
    )
    while _json_size(context) > max_chars:
        removed = False
        for field in trim_fields:
            values = context.get(field)
            if isinstance(values, list) and len(values) > 1:
                values.pop()
                removed = True
                break
        if not removed:
            registry = context.get("canonical_surface_registry")
            if isinstance(registry, dict) and isinstance(registry.get("surfaces"), list) and len(registry["surfaces"]) > 1:
                registry["surfaces"].pop()
                removed = True
        if not removed:
            seeds = context.get("impact_seeds")
            if isinstance(seeds, list) and len(seeds) > 1:
                seeds.pop()
                removed = True
        if not removed:
            candidate_map = context.get("candidate_impact_map")
            if isinstance(candidate_map, dict) and isinstance(candidate_map.get("impacts"), list) and len(candidate_map["impacts"]) > 1:
                candidate_map["impacts"].pop()
                removed = True
        if not removed:
            slice_value = context.get("task_brain_slice", {})
            if isinstance(slice_value, dict):
                for field in (
                    "known_non_goals", "relevant_project_brain_projection", "relevant_dependencies",
                    "current_interfaces", "current_state_ownership", "current_owners", "relevant_tests",
                ):
                    values = slice_value.get(field)
                    if isinstance(values, list) and values:
                        values.pop()
                        removed = True
                        break
        if not removed:
            break
    return context


def _planner_surface_registry_slice(registry):
    value = registry if isinstance(registry, dict) else {}
    result = []
    for surface in list(value.get("surfaces", []) or [])[:MAX_CANONICAL_SURFACES]:
        result.append({
            "surface_id": surface.get("surface_id"),
            "kind": surface.get("kind"),
            "role": surface.get("role"),
            "path": _normal_path(surface.get("path")),
            "symbol": str(surface.get("symbol") or ""),
            "verified_fact": _compact(surface.get("verified_fact"), 280),
            "evidence_ids": _bounded_ids(surface.get("evidence_ids"), MAX_SURFACE_EVIDENCE_IDS),
            "owner_surface_id": surface.get("owner_surface_id"),
        })
    return {
        "version": value.get("version"),
        "surfaces": result,
        "bounds": copy.deepcopy(value.get("bounds", {})),
        "provenance": value.get("provenance", REPOSITORY_EVIDENCE),
    }


def _planner_requirement_projection(requirements):
    return [{
        "requirement_id": item["requirement_id"],
        "text": _compact(item.get("text"), 700),
        "provenance": item.get("provenance", USER_STATED),
    } for item in active_requirements(requirements)]


def _planner_evidence_projection(evidence, selected_surface_ids=None, registry=None):
    """Expose evidence labels without repeating raw repository support."""
    selected = {str(item) for item in list(selected_surface_ids or [])}
    by_id = canonical_surface_by_id(registry)
    evidence_ids = set()
    if selected and by_id:
        for surface_id in selected:
            evidence_ids.update(str(item) for item in by_id.get(surface_id, {}).get("evidence_ids", []) or [])
    result = []
    for item in bounded_evidence(evidence, MAX_CANONICAL_SURFACES * 2):
        if evidence_ids and str(item.get("evidence_id")) not in evidence_ids:
            continue
        result.append({
            "evidence_id": item.get("evidence_id"),
            "category": item.get("category"),
            "path": _normal_path(item.get("path")),
            "symbol": str(item.get("symbol") or ""),
        })
    return result


def _planner_task_fact_projection(task_brain):
    """Make a compact optional Task Brain projection.

    Canonical surfaces and requirements already carry the planning authority;
    this projection is useful only as a small semantic hint and is the first
    Task Brain material removed under context pressure.
    """
    brain = task_brain if isinstance(task_brain, dict) else {}
    result = {}
    fields = (
        "user_confirmed_decisions", "current_owners", "current_state_ownership",
        "current_interfaces", "relevant_tests", "relevant_dependencies",
        "acceptance_conditions", "known_non_goals",
    )
    for field in fields:
        values = []
        for item in list(brain.get(field, []) or [])[:8]:
            if not isinstance(item, dict):
                continue
            value = {
                "text": _compact(item.get("text") or item.get("fact"), 240),
                "requirement_ids": _bounded_ids(item.get("requirement_ids"), 8),
                "evidence_ids": _bounded_ids(item.get("evidence_ids"), 8),
                "path": _normal_path(item.get("path")),
                "symbol": _compact(item.get("symbol"), 160),
                "category": _compact(item.get("category"), 80),
            }
            values.append({key: item for key, item in value.items() if item not in ("", [], None)})
        if values:
            result[field] = values
    return result


def _planner_record_text(item):
    """Extract descriptive text without copying a full structured record."""
    value = item if isinstance(item, dict) else {}
    fact = value.get("fact")
    if isinstance(fact, dict):
        fact = fact.get("fact") or fact.get("text") or fact.get("summary")
    return _compact(
        value.get("text") or fact or value.get("fact_summary")
        or value.get("authority_fact") or value.get("resolution") or "",
        520,
    )


def _planner_source_ids(item):
    value = item if isinstance(item, dict) else {}
    refs = []
    for key in (
        "record_id", "evidence_id", "fact_hash", "semantic_hash", "conflict_id",
        "requirement_id", "authority_record_id",
    ):
        if value.get(key):
            refs.append(str(value[key]))
    refs.extend(str(ref) for ref in list(value.get("requirement_ids", []) or []))
    refs.extend(str(ref) for ref in list(value.get("evidence_ids", []) or []))
    refs.extend(str(ref) for ref in list(value.get("evidence_refs", []) or []))
    refs.extend(str(ref) for ref in list(value.get("repository_evidence_ids", []) or []))
    return list(dict.fromkeys(refs))[:12]


# V24.2 canonical mandatory planning core.  This is deliberately kept in the
# Stage 3 planning module so every role packet uses the same deterministic
# semantic identity rules.  The core is a full structured artifact; only its
# compact ``model_projection`` is placed in a provider-facing packet.
CANONICAL_MANDATORY_PLANNING_CORE_TYPE = "CanonicalMandatoryPlanningCore"
CANONICAL_MANDATORY_PLANNING_CORE_VERSION = "V24.2"
CANONICAL_MANDATORY_CORE_TYPE = CANONICAL_MANDATORY_PLANNING_CORE_TYPE
CANONICAL_MANDATORY_CORE_VERSION = CANONICAL_MANDATORY_PLANNING_CORE_VERSION

_CORE_KIND_ORDER = (
    "desired", "ownership", "interface", "preservation", "prohibition",
    "dnt", "conflict", "current", "surface", "impact", "metadata",
)
_CORE_ALIAS_PREFIX = {
    "desired": "REQ",
    "ownership": "AUTH",
    "interface": "IFACE",
    "preservation": "PRES",
    "prohibition": "PROH",
    "dnt": "DNT",
    "conflict": "CONFLICT",
    "current": "STATE",
    "surface": "SURF",
    "impact": "IMPACT",
    "metadata": "META",
}
_CORE_SEMANTIC_KIND_PRIORITY = {
    "desired": 0, "conflict": 1, "ownership": 2, "interface": 3,
    "preservation": 4, "prohibition": 5, "dnt": 6, "current": 7,
    "surface": 8, "impact": 9, "metadata": 10,
}


def _core_normalize_text(value):
    """Normalize prose for exact identity checks, never fuzzy equivalence."""
    return " ".join(str(value or "").split()).casefold()


def _core_slug(value, limit=42):
    text = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").upper()).strip("-")
    text = re.sub(r"-+", "-", text)
    if not text:
        return "ITEM"
    if len(text) <= limit:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8].upper()
    return text[: max(1, limit - 9)].rstrip("-") + "-" + digest


def _core_text(item, limit=MAX_TEXT_CHARS):
    value = item if isinstance(item, dict) else {}
    raw = (
        value.get("meaning") or value.get("text") or value.get("verified_fact")
        or value.get("fact") or value.get("fact_summary") or value.get("authority_fact")
        or value.get("resolution") or value.get("reason") or value.get("value") or ""
    )
    if isinstance(raw, dict):
        raw = raw.get("fact") or raw.get("text") or raw.get("summary") or ""
    return _compact(raw, limit)


def _core_path(item):
    value = item if isinstance(item, dict) else {}
    return _normal_path(value.get("path") or value.get("canonical_path") or value.get("verified_path"))


def _core_symbol(item):
    value = item if isinstance(item, dict) else {}
    return _compact(value.get("symbol") or value.get("canonical_symbol") or value.get("verified_symbol"), 180)


def _core_relation(item):
    """Return an explicitly structured relation, without parsing prose."""
    value = item if isinstance(item, dict) else {}
    candidates = [
        value.get("semantic_relation"), value.get("structured_relation"),
        value.get("authority_relation"), value.get("repository_relation"),
        value.get("relation"),
    ]
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        subject = raw.get("subject") or raw.get("domain")
        predicate = raw.get("predicate") or raw.get("relationship")
        obj = raw.get("object") or raw.get("owner") or raw.get("owner_entity")
        if subject and predicate and obj:
            return {
                "subject": _core_normalize_text(subject),
                "predicate": _core_normalize_text(predicate),
                "object": _core_normalize_text(obj),
            }
    return None


def _core_source_references(item):
    """Collect full source IDs and hashes for the immutable provenance map."""
    value = item if isinstance(item, dict) else {}
    record_ids = []
    hashes = []
    reference_keys = (
        "record_id", "source_record_id", "authority_record_id", "requirement_id",
        "evidence_id", "conflict_id", "constraint_id", "seed_id", "surface_id", "impact_id",
    )
    list_keys = (
        "source_id", "source_ids", "source_record_ids", "source_refs", "provenance_refs",
        "evidence_ids", "evidence_refs", "repository_evidence_ids",
        "requirement_ids", "authority_record_ids", "repository_evidence_id",
        "current_authority_ids", "current_evidence_ids", "desired_requirement_ids",
        "interface_ids", "surface_ids", "impact_ids", "conflict_ids",
        "preservation_ids", "prohibition_ids", "dnt_ids",
    )
    hash_keys = (
        "fact_hash", "semantic_hash", "authority_fact_hash", "file_sha256",
        "source_hash", "source_hashes", "promotion_hash", "promotion_hashes",
        "reentry_hash", "task_brain_hash", "planning_context_hash",
        "source_planning_context_hash", "source_task_brain_hash", "source_reentry_hash",
        "source_promotion_hash", "source_promotion_hashes", "source_repository_evidence_hash",
        "source_project_brain_hash", "source_provenance_hash", "source_context_hash",
    )
    for key in reference_keys:
        raw = value.get(key)
        if raw not in (None, "", [], {}):
            record_ids.append(str(raw))
    for key in list_keys:
        raw = value.get(key)
        values = list(raw) if isinstance(raw, (list, tuple, set)) else [raw]
        for item_value in values:
            if item_value not in (None, "", [], {}):
                record_ids.append(str(item_value))
    for key in hash_keys:
        raw = value.get(key)
        values = list(raw) if isinstance(raw, (list, tuple, set)) else [raw]
        for item_value in values:
            if item_value not in (None, "", [], {}):
                hashes.append(str(item_value))
    # Some structured artifacts nest provenance under a ``source_provenance``
    # or ``provenance`` object.  Read only explicitly ID/hash-shaped fields;
    # do not serialize arbitrary metadata or classify prose as provenance.
    for nested_key in ("source_provenance", "provenance"):
        nested = value.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key, raw in nested.items():
            key_text = str(key).casefold()
            values = list(raw) if isinstance(raw, (list, tuple, set)) else [raw]
            for item_value in values:
                if item_value in (None, "", [], {}):
                    continue
                if "hash" in key_text:
                    hashes.append(str(item_value))
                elif key_text.endswith("id") or key_text.endswith("ids") or "ref" in key_text:
                    record_ids.append(str(item_value))
    record_ids = sorted(set(record_ids))
    hashes = sorted(set(hashes))
    references = sorted(set(record_ids + hashes))
    return record_ids, hashes, references


def _core_item_kind(section, item):
    """Map an already structured source section to a semantic category."""
    value = item if isinstance(item, dict) else {}
    section = str(section or "").casefold()
    category = str(value.get("category") or value.get("field") or "").casefold()
    authority_type = " ".join(
        [str(value.get("authority_type") or "")] + [
            str(item) for item in list(value.get("authority_types", []) or [])
        ]
    ).casefold()
    if section in {"requirements", "task_goal", "desired_obligations"}:
        return "desired"
    if section in {"surfaces", "surface_bindings"}:
        return "surface"
    if section in {"impact_seeds", "impact_slots"}:
        return "impact"
    if section in {"confirmed_conflicts", "conflicts"}:
        return "conflict"
    if section in {"dnt", "do_not_touch"}:
        return "dnt"
    if section in {"prohibitions", "prohibition_constraints"}:
        return "prohibition"
    if section in {"preservation_constraints", "preservation_obligations"}:
        return "preservation"
    if section in {"interfaces", "current_interfaces", "current_interface"}:
        return "interface"
    if section in {"current_ownership", "current_authority", "current_owners", "current_state_ownership"}:
        if (
            "interface" in category or "interface" in authority_type
            or "toggle" in str(value.get("symbol") or "").casefold()
        ):
            return "interface"
        if (
            "owner" in category or "ownership" in category
            or "owner" in authority_type or "ownership" in authority_type
            or value.get("owner") or value.get("owner_entity")
        ):
            return "ownership"
        if value.get("structured_relation") or value.get("authority_relation"):
            relation = _core_relation(value) or {}
            if str(relation.get("predicate", "")).casefold() in {"owner", "owns", "owned_by", "ownership"}:
                return "ownership"
        text = _core_text(value)
        if re.search(r"\b(?:sole|only|owner|ownership|state owner)\b", text, re.IGNORECASE):
            return "ownership"
        if re.search(r"\b(?:interface|toggle|api|handler)\b", text, re.IGNORECASE):
            return "interface"
        if re.search(r"\b(?:preserv|retain|remain|escape|movement|unchanged)\b", text, re.IGNORECASE):
            return "preservation"
        return "current"
    if section in {"planning_provenance", "current_vs_desired", "planning_rules", "bounds", "metadata"}:
        return "metadata"
    if "interface" in category or "interface" in authority_type:
        return "interface"
    if "owner" in category or "ownership" in category or "owner" in authority_type:
        return "ownership"
    if "prohibit" in category or "dnt" in category:
        return "prohibition"
    return "current"


def _core_explicit_identity(item):
    value = item if isinstance(item, dict) else {}
    for key in ("canonical_semantic_id", "semantic_id", "semantic_key"):
        raw = value.get(key)
        if raw not in (None, "", [], {}):
            return "EXPLICIT:" + _core_normalize_text(raw)
    relation = _core_relation(value)
    if relation:
        return "RELATION:" + _compact_json(relation)
    return ""


def _core_identity_key(kind, item, *, requirement_texts=None):
    value = item if isinstance(item, dict) else {}
    explicit = _core_explicit_identity(value)
    if explicit:
        return explicit
    if kind == "desired":
        requirement_id = value.get("requirement_id") or value.get("id")
        if requirement_id:
            return "REQUIREMENT:" + str(requirement_id)
    text = _core_normalize_text(_core_text(value, 900))
    if requirement_texts and text in requirement_texts:
        return "REQUIREMENT:" + str(requirement_texts[text])
    path = _core_path(value)
    symbol = _core_symbol(value)
    if kind == "dnt" and path:
        return "DNT_PATH:" + path.casefold()
    if kind == "surface" and value.get("surface_id"):
        return "SURFACE:" + str(value.get("surface_id"))
    if kind == "impact" and value.get("impact_id"):
        return "IMPACT:" + str(value.get("impact_id"))
    if kind == "conflict" and value.get("conflict_id"):
        return "CONFLICT:" + str(value.get("conflict_id"))
    if kind in {"ownership", "interface"} and (path or symbol):
        return f"{kind.upper()}_LOCATION:{path.casefold()}:{symbol.casefold()}:{str(value.get('field') or value.get('category') or '').casefold()}"
    if text:
        return "TEXT:" + text
    if path:
        return f"{kind.upper()}_PATH:{path.casefold()}"
    # Unknown relations are never collapsed into one bucket.  A structured
    # candidate has a stable section/index; a raw audit unit gets a stable
    # kind-local fallback.  This is intentionally not a fuzzy equivalence.
    section = value.get("section")
    index = value.get("index")
    if section is not None and index is not None:
        return f"UNRESOLVED:{kind}:{section}:{index}"
    return f"UNRESOLVED:{kind}:{_core_normalize_text(_core_text(value, 900))}"


def _core_semantic_id(kind, identity):
    prefix = _CORE_ALIAS_PREFIX.get(kind, "META")
    if identity.startswith("REQUIREMENT:"):
        return "REQ-" + _core_slug(identity.split(":", 1)[1], 44)
    if identity.startswith("RELATION:"):
        relation = identity.split(":", 1)[1]
        if '"predicate":"owner"' in relation or '"predicate":"owns"' in relation:
            prefix = "AUTH"
        elif '"predicate":"interface"' in relation or '"predicate":"exposes"' in relation:
            prefix = "IFACE"
    if identity.startswith("DNT_PATH:"):
        prefix = "DNT"
    if identity.startswith("SURFACE:"):
        return str(identity.split(":", 1)[1])
    if identity.startswith("IMPACT:"):
        return str(identity.split(":", 1)[1])
    if identity.startswith("CONFLICT:"):
        prefix = "CONFLICT"
    readable = identity.split(":", 1)[1] if ":" in identity else identity
    return prefix + "-" + _core_slug(readable, 40)


def _core_candidate(
    units, section, kind, item, index, *, model_required=True, meaning=None,
):
    value = item if isinstance(item, dict) else {"value": item}
    record_ids, hashes, references = _core_source_references(value)
    requirement_refs = list(value.get("requirement_ids") or [])
    if value.get("requirement_id"):
        requirement_refs.append(value.get("requirement_id"))
    unit = {
        "section": str(section),
        "index": int(index),
        "kind": kind,
        "model_required": bool(model_required),
        "meaning": _compact(meaning if meaning is not None else _core_text(value, 900), 900),
        "path": _core_path(value),
        "symbol": _core_symbol(value),
        "requirement_ids": sorted(set(_bounded_ids(requirement_refs, MAX_REQUIREMENT_REFS_PER_IMPACT))),
        "evidence_ids": sorted(set(_bounded_ids(
            value.get("evidence_ids") or value.get("evidence_refs")
            or value.get("repository_evidence_ids"), MAX_SURFACE_EVIDENCE_IDS,
        ))),
        "source_record_ids": record_ids,
        "source_hashes": hashes,
        "source_references": references,
    }
    relation = _core_relation(value)
    if relation:
        unit["semantic_relation"] = relation
    for identity_key in ("canonical_semantic_id", "semantic_id", "semantic_key"):
        if value.get(identity_key) not in (None, "", [], {}):
            unit["canonical_semantic_id"] = str(value.get(identity_key))
            break
    units.append(unit)
    return unit


def _core_model_kind(unit):
    kinds = set(unit.get("kinds", []) or [])
    if not kinds:
        kinds = {unit.get("kind", "metadata")}
    return min(kinds, key=lambda item: _CORE_SEMANTIC_KIND_PRIORITY.get(item, 99))


def _core_merge_unit(existing, candidate):
    existing["kinds"] = sorted(set(existing.get("kinds", [])) | {candidate.get("kind")})
    existing["sections"] = sorted(set(existing.get("sections", [])) | {candidate.get("section")})
    existing["source_record_ids"] = sorted(set(existing.get("source_record_ids", [])) | set(candidate.get("source_record_ids", [])))
    existing["source_hashes"] = sorted(set(existing.get("source_hashes", [])) | set(candidate.get("source_hashes", [])))
    existing["source_references"] = sorted(set(existing.get("source_references", [])) | set(candidate.get("source_references", [])))
    existing["requirement_ids"] = sorted(set(existing.get("requirement_ids", [])) | set(candidate.get("requirement_ids", [])))
    existing["evidence_ids"] = sorted(set(existing.get("evidence_ids", [])) | set(candidate.get("evidence_ids", [])))
    existing["model_required"] = bool(existing.get("model_required") or candidate.get("model_required"))
    if not existing.get("semantic_relation") and candidate.get("semantic_relation"):
        existing["semantic_relation"] = copy.deepcopy(candidate.get("semantic_relation"))
    if not existing.get("canonical_semantic_id") and candidate.get("canonical_semantic_id"):
        existing["canonical_semantic_id"] = str(candidate.get("canonical_semantic_id"))
    meanings = [item for item in (existing.get("meaning"), candidate.get("meaning")) if item]
    if meanings:
        existing["meaning"] = min(meanings, key=lambda item: (len(str(item)), _core_normalize_text(item), str(item)))
    locations = [
        (existing.get("path", ""), existing.get("symbol", "")),
        (candidate.get("path", ""), candidate.get("symbol", "")),
    ]
    locations = sorted({(str(path), str(symbol)) for path, symbol in locations if path or symbol})
    if locations:
        existing["path"], existing["symbol"] = locations[0]


def _core_model_entry(unit, alias):
    value = {"id": alias}
    meaning = str(unit.get("meaning") or "").strip()
    if meaning:
        value["meaning"] = _compact(meaning, 520)
    if unit.get("path"):
        value["path"] = unit.get("path")
    if unit.get("symbol"):
        value["symbol"] = unit.get("symbol")
    if unit.get("requirement_ids"):
        value["requirement_ids"] = list(unit.get("requirement_ids", []))[:MAX_REQUIREMENT_REFS_PER_IMPACT]
    aliases = [str(item) for item in list(unit.get("aliases", []) or []) if str(item)]
    if len(aliases) > 1:
        value["semantic_refs"] = aliases
    return value


def build_canonical_mandatory_planning_core(
    payload=None, *, project_id=None, task_id=None,
    source_planning_context_hash=None, source_task_brain_hash=None,
    source_reentry_hash=None,
):
    """Build the immutable V24.2 semantic mandatory core with provenance fan-in.

    Only explicit semantic IDs, explicit structured relations, exact normalized
    text, or exact canonical locations are used for equivalence.  Unknown
    relationships remain separate.  Full source IDs and hashes are retained in
    ``provenance_map``; the provider projection contains concise meanings and
    role-local aliases only.
    """
    value = payload if isinstance(payload, dict) else {}
    candidates = []
    requirement_texts = {}
    requirements = list(value.get("requirements", []) or [])
    if not requirements:
        requirements = list(value.get("new_requirements", []) or [])
    for index, item in enumerate(requirements):
        if not isinstance(item, dict):
            continue
        requirement_id = str(item.get("requirement_id") or item.get("id") or "")
        text = _core_normalize_text(_core_text(item, 900))
        if requirement_id and text:
            requirement_texts[text] = requirement_id
        _core_candidate(candidates, "requirements", "desired", item, index, meaning=_core_text(item, 900))

    goal = value.get("task_goal")
    if isinstance(goal, dict):
        goal_item = copy.deepcopy(goal)
    else:
        goal_item = {"text": goal}
    if _core_text(goal_item, 900):
        _core_candidate(
            candidates, "task_goal", "desired", goal_item, 0,
            meaning=_core_text(goal_item, 900),
        )

    for section, kind, model_required in (
        ("current_authority", "current", True),
        ("current_durable_authority", "current", True),
        ("current_verified_facts", "current", True),
        ("current_owners", "ownership", True),
        ("current_state_ownership", "ownership", True),
        ("current_interfaces", "interface", True),
        ("interfaces", "interface", True),
        ("preservation_constraints", "preservation", True),
        ("prohibitions", "prohibition", True),
        ("dnt", "dnt", True),
        ("confirmed_conflicts", "conflict", True),
        ("conflicts", "conflict", True),
        ("surfaces", "surface", True),
        ("impact_seeds", "impact", True),
    ):
        for index, item in enumerate(list(value.get(section, []) or [])):
            if not isinstance(item, dict):
                continue
            effective_kind = _core_item_kind(section, item)
            # Section authority is stronger than a loose prose classifier for
            # explicitly typed DNT, prohibition, interface, and conflict data.
            if section in {"interfaces", "preservation_constraints", "prohibitions", "dnt", "confirmed_conflicts", "surfaces", "impact_seeds"}:
                effective_kind = kind
            _core_candidate(
                candidates, section, effective_kind, item, index,
                model_required=model_required,
                meaning=_core_text(item, 520),
            )

    # Empty current-authority objects can still carry validator-essential
    # provenance.  Keep their references in the full core without spending
    # model characters on an uninformative prose item.
    for section in (
        "planning_provenance", "source_provenance", "current_vs_desired",
        "planning_rules", "bounds",
    ):
        raw = value.get(section)
        if isinstance(raw, list):
            values = list(raw)
        elif isinstance(raw, dict):
            values = [raw]
        elif raw not in (None, "", [], {}):
            values = [{"value": raw}]
        else:
            values = []
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                item = {"value": item}
            _core_candidate(
                candidates, section, "metadata", item, index,
                model_required=False, meaning=_core_text(item, 520),
            )
    for index, item in enumerate(list(value.get("current_repository_evidence", []) or [])):
        if isinstance(item, dict):
            _core_candidate(
                candidates, "current_repository_evidence", "metadata", item, index,
                model_required=False, meaning=_core_text(item, 520),
            )

    # Requirement identity is established before current authority and
    # preservation candidates, allowing exact repeated requirement statements
    # to fan into the one desired semantic unit.
    grouped = {}
    identity_for_candidate = {}
    for candidate in candidates:
        identity = _core_identity_key(
            candidate.get("kind"), candidate,
            requirement_texts=requirement_texts,
        )
        # The candidate's extracted fields are intentionally used here rather
        # than the original arbitrary object.  This makes the identity stable
        # after bounded projection while retaining full references separately.
        if candidate.get("kind") == "desired":
            requirement_id = next(iter(candidate.get("requirement_ids", [])), None)
            if requirement_id and candidate.get("section") == "requirements":
                identity = "REQUIREMENT:" + str(requirement_id)
        identity_for_candidate[id(candidate)] = identity
        if identity not in grouped:
            grouped[identity] = {
                "identity_key": identity,
                "semantic_id": "",
                "kinds": [candidate.get("kind")],
                "sections": [candidate.get("section")],
                "model_required": bool(candidate.get("model_required")),
                "meaning": candidate.get("meaning", ""),
                "path": candidate.get("path", ""),
                "symbol": candidate.get("symbol", ""),
                "requirement_ids": list(candidate.get("requirement_ids", [])),
                "evidence_ids": list(candidate.get("evidence_ids", [])),
                "source_record_ids": list(candidate.get("source_record_ids", [])),
                "source_hashes": list(candidate.get("source_hashes", [])),
                "source_references": list(candidate.get("source_references", [])),
            }
        else:
            _core_merge_unit(grouped[identity], candidate)

    units = []
    for identity, unit in grouped.items():
        kind = _core_model_kind(unit)
        unit["semantic_id"] = _core_semantic_id(kind, identity)
        unit["kinds"] = sorted(set(unit.get("kinds", [])), key=lambda item: _CORE_SEMANTIC_KIND_PRIORITY.get(item, 99))
        unit["sections"] = sorted(set(unit.get("sections", [])))
        for key in ("requirement_ids", "evidence_ids", "source_record_ids", "source_hashes", "source_references"):
            unit[key] = sorted(set(str(item) for item in unit.get(key, []) if str(item)))
        units.append(unit)
    # Semantic IDs are stable independently of source-record order.
    units.sort(key=lambda item: (_CORE_SEMANTIC_KIND_PRIORITY.get(_core_model_kind(item), 99), item.get("semantic_id", ""), item.get("identity_key", "")))

    units_by_kind = {kind: [] for kind in _CORE_KIND_ORDER}
    for unit in units:
        for kind in unit.get("kinds", []) or [_core_model_kind(unit)]:
            units_by_kind.setdefault(kind, []).append(unit)
    for kind in units_by_kind:
        units_by_kind[kind] = sorted(
            {unit.get("semantic_id"): unit for unit in units_by_kind[kind]}.values(),
            key=lambda item: item.get("semantic_id", ""),
        )

    alias_by_kind = {}
    semantic_alias_map = {}
    for kind in _CORE_KIND_ORDER:
        for index, unit in enumerate(units_by_kind.get(kind, []), 1):
            alias = f"{_CORE_ALIAS_PREFIX.get(kind, 'META')}-{index}"
            alias_by_kind.setdefault(kind, {})[unit.get("semantic_id")] = alias
            semantic_alias_map[alias] = {
                "semantic_id": unit.get("semantic_id"),
                "category": kind,
            }
    for unit in units:
        aliases = []
        for kind in unit.get("kinds", []) or [_core_model_kind(unit)]:
            alias = alias_by_kind.get(kind, {}).get(unit.get("semantic_id"))
            if alias and alias not in aliases:
                aliases.append(alias)
        unit["aliases"] = aliases

    provenance_map = {}
    for unit in units:
        provenance_map[unit["semantic_id"]] = {
            "source_record_ids": list(unit.get("source_record_ids", [])),
            "source_hashes": list(unit.get("source_hashes", [])),
            "source_references": list(unit.get("source_references", [])),
            "source_sections": list(unit.get("sections", [])),
        }

    def aliases_for(kind):
        return [
            alias_by_kind.get(kind, {}).get(item.get("semantic_id"))
            for item in units_by_kind.get(kind, [])
            if alias_by_kind.get(kind, {}).get(item.get("semantic_id"))
        ]

    def primary_alias(item):
        primary_kind = _core_model_kind(item)
        return alias_by_kind.get(primary_kind, {}).get(item.get("semantic_id"))

    def model_entries(kind):
        """Render each semantic meaning once, with category-only fan-in refs."""
        entries = []
        for item in units_by_kind.get(kind, []):
            if not item.get("model_required"):
                continue
            alias = alias_by_kind.get(kind, {}).get(item.get("semantic_id"))
            if not alias:
                continue
            primary_kind = _core_model_kind(item)
            if primary_kind == kind:
                entries.append(_core_model_entry(item, alias))
            else:
                # The meaning is emitted under its canonical primary category.
                # This short reference preserves that the same semantic unit
                # also participates in this category without repeating prose.
                entry = {"id": alias, "ref": primary_alias(item)}
                secondary_aliases = [
                    alias_by_kind.get(other_kind, {}).get(item.get("semantic_id"))
                    for other_kind in item.get("kinds", [])
                    if other_kind != primary_kind
                ]
                secondary_aliases = [str(ref) for ref in secondary_aliases if ref]
                if secondary_aliases:
                    entry["semantic_refs"] = secondary_aliases
                entries.append(entry)
        return entries

    desired_ids = aliases_for("desired")
    current_ids = []
    for kind in ("ownership", "interface", "preservation", "prohibition", "dnt", "conflict", "current"):
        for alias in aliases_for(kind):
            if alias not in current_ids:
                current_ids.append(alias)
    desired_requirement_ids = sorted({
        str(item.get("requirement_id")) for item in requirements
        if isinstance(item, dict) and item.get("requirement_id")
    })
    current_project_state = {
        "ownership": model_entries("ownership"),
        "interfaces": model_entries("interface"),
        "preservation": model_entries("preservation"),
        "prohibitions": model_entries("prohibition"),
        "dnt": model_entries("dnt"),
        "confirmed_conflicts": model_entries("conflict"),
        "other_authority": model_entries("current"),
    }
    current_project_state = {
        key: item for key, item in current_project_state.items() if item
    }
    model_projection = {
        "version": 1,
        "desired_user_change": model_entries("desired"),
        "current_project_state": current_project_state,
        "current_vs_desired": {
            "desired": desired_ids,
            "current": current_ids,
            "desired_requirement_ids": desired_requirement_ids,
        },
        "planning_rules": list(value.get("planning_rules", []) or []),
    }

    # ``requirements`` is the authoritative user-facing rendering of a
    # requirement.  A canonical desired unit that fans in that requirement is
    # represented by its ID/relationship only, so the same prose is not
    # printed a second time in ``mandatory_core.desired_user_change``.
    requirement_ids = {
        str(item.get("requirement_id") or item.get("id"))
        for item in requirements
        if isinstance(item, dict) and (item.get("requirement_id") or item.get("id"))
    }
    if requirement_ids:
        desired_refs = []
        for entry in model_projection.get("desired_user_change", []):
            if not isinstance(entry, dict):
                continue
            entry_requirement_ids = {
                str(item) for item in list(entry.get("requirement_ids", []) or [])
            }
            if entry_requirement_ids & requirement_ids:
                desired_refs.append({
                    key: copy.deepcopy(entry[key])
                    for key in ("id", "requirement_ids", "semantic_refs")
                    if key in entry
                })
            else:
                desired_refs.append(entry)
        model_projection["desired_user_change"] = desired_refs

    # Every original mandatory unit is covered by a canonical semantic unit or
    # by a validator-only provenance unit.  No source reference is discarded.
    projection_aliases = set()
    for section_name, section_value in model_projection.items():
        if section_name == "current_vs_desired" and isinstance(section_value, dict):
            for relation_value in section_value.values():
                if isinstance(relation_value, list):
                    projection_aliases.update(str(item) for item in relation_value)
                elif isinstance(relation_value, dict):
                    projection_aliases.update(str(item) for item in relation_value.values())
            continue
        if isinstance(section_value, dict):
            nested_values = section_value.values()
        elif isinstance(section_value, list):
            nested_values = section_value
        else:
            nested_values = []
        for item in nested_values:
            if isinstance(item, dict):
                for key in ("id", "ref", "semantic_refs"):
                    raw = item.get(key)
                    if isinstance(raw, list):
                        projection_aliases.update(str(value) for value in raw)
                    elif raw not in (None, ""):
                        projection_aliases.add(str(raw))
    coverage = []
    for candidate in candidates:
        identity = identity_for_candidate.get(id(candidate), "")
        unit = grouped.get(identity)
        canonical_id = unit.get("semantic_id") if unit else ""
        source_references = list(candidate.get("source_references", []))
        stable_original_id = (
            candidate.get("semantic_id")
            or (
                f"{candidate.get('section')}:{source_references[0]}"
                if source_references else
                f"{candidate.get('section')}:{candidate.get('kind')}:"
                f"{_core_normalize_text(candidate.get('meaning'))}:"
                f"{_core_path(candidate)}:{_core_symbol(candidate)}"
            )
        )
        model_backed_by_packet = candidate.get("section") in {
            "requirements", "task_goal", "surfaces", "impact_seeds",
        }
        model_aliases = set(unit.get("aliases", [])) if unit else set()
        model_semantic_represented = bool(
            model_backed_by_packet or model_aliases.intersection(projection_aliases)
        )
        coverage.append({
            "original_semantic_id": str(stable_original_id),
            "canonical_semantic_id": canonical_id,
            "category": candidate.get("kind"),
            "represented": bool(unit),
            "source_provenance_retained": bool(
                unit and set(source_references)
                .issubset(set(unit.get("source_references", [])))
            ),
            "model_semantic_required": bool(candidate.get("model_required")),
            "model_semantic_represented": model_semantic_represented,
            "source_record_ids": list(candidate.get("source_record_ids", [])),
            "source_hashes": list(candidate.get("source_hashes", [])),
            "source_references": source_references,
        })
    coverage.sort(key=lambda item: (str(item.get("original_semantic_id")), str(item.get("canonical_semantic_id"))))

    all_source_references = sorted({
        str(reference)
        for candidate in candidates
        for reference in candidate.get("source_references", [])
        if str(reference)
    })
    coverage_rate = (
        sum(bool(
            item.get("represented")
            and item.get("source_provenance_retained")
            and (
                not item.get("model_semantic_required")
                or item.get("model_semantic_represented")
            )
        ) for item in coverage)
        / len(coverage) if coverage else 1.0
    )
    core_metrics = {
        "mandatory_planning_records_input": len(candidates),
        "mandatory_semantic_units": len(units),
        "mandatory_semantic_units_deduplicated": max(0, len(candidates) - len(units)),
        "mandatory_provenance_refs": len(all_source_references),
        "mandatory_model_chars_before_normalization": len(_compact_json(value)),
        "mandatory_model_chars_after_normalization": len(_compact_json(model_projection)),
        "mandatory_semantic_coverage": coverage_rate,
        "planning_core_model_calls": 0,
    }
    source_metadata = value.get("planning_provenance") if isinstance(value.get("planning_provenance"), dict) else {}
    if not source_metadata and isinstance(value.get("source_provenance"), dict):
        source_metadata = value.get("source_provenance")
    project_id = project_id if project_id is not None else value.get("project_id")
    task_id = task_id if task_id is not None else value.get("task_id")
    source_planning_context_hash = (
        source_planning_context_hash or source_metadata.get("source_planning_context_hash")
        or value.get("planning_context_hash") or value.get("verified_planning_context_hash")
    )
    source_task_brain_hash = (
        source_task_brain_hash or source_metadata.get("source_task_brain_hash")
        or value.get("task_brain_hash")
    )
    source_reentry_hash = (
        source_reentry_hash or source_metadata.get("source_reentry_hash")
        or value.get("reentry_hash")
    )
    core = {
        "version": 1,
        "artifact_type": CANONICAL_MANDATORY_PLANNING_CORE_TYPE,
        "schema_version": CANONICAL_MANDATORY_PLANNING_CORE_VERSION,
        "project_id": project_id,
        "task_id": task_id,
        "desired_obligations": [
            copy.deepcopy(item) for item in units_by_kind.get("desired", [])
            if item.get("model_required")
        ],
        "current_ownership": [
            copy.deepcopy(item) for item in units_by_kind.get("ownership", [])
            if item.get("model_required")
        ],
        "current_interfaces": [
            copy.deepcopy(item) for item in units_by_kind.get("interface", [])
            if item.get("model_required")
        ],
        "preservation_obligations": [
            copy.deepcopy(item) for item in units_by_kind.get("preservation", [])
            if item.get("model_required")
        ],
        "prohibitions": [
            copy.deepcopy(item) for item in units_by_kind.get("prohibition", [])
            if item.get("model_required")
        ],
        "dnt": [
            copy.deepcopy(item) for item in units_by_kind.get("dnt", [])
            if item.get("model_required")
        ],
        "confirmed_conflicts": [
            copy.deepcopy(item) for item in units_by_kind.get("conflict", [])
            if item.get("model_required")
        ],
        "semantic_units": copy.deepcopy(units),
        "semantic_alias_map": {
            key: semantic_alias_map[key] for key in sorted(semantic_alias_map)
        },
        "provenance_map": {
            key: provenance_map[key] for key in sorted(provenance_map)
        },
        "mandatory_semantic_coverage": coverage,
        "metrics": core_metrics,
        "model_projection": model_projection,
        "source_planning_context_hash": source_planning_context_hash,
        "source_task_brain_hash": source_task_brain_hash,
        "source_reentry_hash": source_reentry_hash,
    }
    core_material = copy.deepcopy(core)
    core["mandatory_core_hash"] = hashlib.sha256(
        _compact_json(core_material).encode("utf-8")
    ).hexdigest()
    core["canonical_mandatory_core_hash"] = core["mandatory_core_hash"]
    core["mandatory_semantic_coverage_rate"] = coverage_rate
    return core


compile_canonical_mandatory_planning_core = build_canonical_mandatory_planning_core
build_canonical_mandatory_core = build_canonical_mandatory_planning_core
build_mandatory_planning_core = build_canonical_mandatory_planning_core


def canonical_mandatory_core_hash(core):
    value = copy.deepcopy(core if isinstance(core, dict) else {})
    value.pop("mandatory_core_hash", None)
    value.pop("canonical_mandatory_core_hash", None)
    value.pop("mandatory_semantic_coverage_rate", None)
    return hashlib.sha256(_compact_json(value).encode("utf-8")).hexdigest()


canonical_mandatory_planning_core_hash = canonical_mandatory_core_hash


def validate_canonical_mandatory_planning_core(core):
    value = core if isinstance(core, dict) else {}
    errors = []
    if value.get("artifact_type") != CANONICAL_MANDATORY_PLANNING_CORE_TYPE:
        errors.append("wrong canonical mandatory core artifact type")
    if value.get("schema_version") != CANONICAL_MANDATORY_PLANNING_CORE_VERSION:
        errors.append("wrong canonical mandatory core schema version")
    if value.get("mandatory_core_hash") != canonical_mandatory_core_hash(value):
        errors.append("mandatory core hash does not match canonical contents")
    if not isinstance(value.get("semantic_alias_map"), dict):
        errors.append("semantic alias map is missing")
    if not isinstance(value.get("provenance_map"), dict):
        errors.append("provenance map is missing")
    coverage = value.get("mandatory_semantic_coverage")
    if not isinstance(coverage, list):
        errors.append("mandatory semantic coverage is missing")
    else:
        for item in coverage:
            if not isinstance(item, dict) or not item.get("represented"):
                errors.append("mandatory semantic coverage is incomplete")
                break
            if item.get("model_semantic_required") and item.get("model_semantic_represented") is not True:
                errors.append("mandatory model semantic is not represented")
                break
            if item.get("source_record_ids") and item.get("source_provenance_retained") is not True:
                errors.append("mandatory source provenance is not retained")
                break
    for semantic_id, provenance in (value.get("provenance_map") or {}).items():
        if not isinstance(provenance, dict):
            errors.append(f"provenance entry is malformed: {semantic_id}")
            break
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:24],
        "mandatory_semantic_coverage": (
            sum(bool(
                item.get("represented")
                and item.get("source_provenance_retained")
                and (
                    not item.get("model_semantic_required")
                    or item.get("model_semantic_represented")
                )
            ) for item in coverage) / len(coverage) if coverage else 1.0
        ) if isinstance(coverage, list) else 0.0,
        "provenance_entries": len(value.get("provenance_map", {}) or {}),
        "model_calls": 0,
    }


validate_canonical_mandatory_core = validate_canonical_mandatory_planning_core
validate_mandatory_planning_core = validate_canonical_mandatory_planning_core


def audit_mandatory_planning_payload(payload):
    """Break down a mandatory payload using exact complete semantic units."""
    value = payload if isinstance(payload, dict) else {}
    requirement_texts = {
        _core_normalize_text(_core_text(item, 900)): str(item.get("requirement_id") or item.get("id"))
        for item in list(value.get("requirements", []) or [])
        if isinstance(item, dict) and (item.get("requirement_id") or item.get("id"))
    }
    units = []
    section_order = list(value.keys())
    for section_index, section in enumerate(section_order):
        raw = value.get(section)
        if isinstance(raw, list):
            values = list(raw)
        else:
            values = [raw]
        if raw in (None, "", [], {}):
            continue
        for index, item in enumerate(values):
            item_value = item if isinstance(item, dict) else {"value": item}
            kind = _core_item_kind(section, item_value)
            identity_item = copy.deepcopy(item_value)
            identity_item["section"] = str(section)
            identity_item["index"] = index
            identity = _core_identity_key(
                kind, identity_item, requirement_texts=requirement_texts,
            )
            record_ids, hashes, references = _core_source_references(item_value)
            meaning = _core_text(item_value, 900)
            rendered = _compact_json({section: item})
            units.append({
                "unit_id": f"{section}:{index}",
                "section": str(section),
                "index": index,
                "category": kind,
                "semantic_identity": identity,
                "semantic_meaning": meaning,
                "source_record_ids": record_ids,
                "source_hashes": hashes,
                "source_references": references,
                "rendered_chars": len(rendered),
                "full_provenance_inline_required": False,
                "provenance_is_validator_metadata": bool(references and not meaning),
            })
    by_identity = {}
    for unit in units:
        by_identity.setdefault(unit["semantic_identity"], []).append(unit["unit_id"])
    for unit in units:
        overlaps = [item for item in by_identity.get(unit["semantic_identity"], []) if item != unit["unit_id"]]
        unit["semantic_overlap"] = bool(overlaps)
        unit["overlap_unit_ids"] = overlaps
        if overlaps:
            unit["overlap_type"] = (
                "STRUCTURED_IDENTITY" if unit["semantic_identity"].startswith(("EXPLICIT:", "RELATION:", "OWNERSHIP_LOCATION:", "INTERFACE_LOCATION:"))
                else "EXACT_NORMALIZED_SEMANTICS"
            )
        else:
            unit["overlap_type"] = None
    duplicate_groups = [
        {"semantic_identity": key, "unit_ids": sorted(item)}
        for key, item in sorted(by_identity.items()) if len(item) > 1
    ]
    return {
        "artifact_type": "MandatoryPlanningPayloadAudit",
        "payload_chars": len(_compact_json(value)),
        "rendered_chars": len(_compact_json(value)),
        "unit_count": len(units),
        "units": units,
        "mandatory_units": copy.deepcopy(units),
        "duplicate_semantic_groups": duplicate_groups,
        "exact_duplicate_groups": [
            item for item in duplicate_groups
            if any(unit.get("overlap_type") == "EXACT_NORMALIZED_SEMANTICS" for unit in units if unit["unit_id"] in item["unit_ids"])
        ],
        "structured_overlap_groups": [
            item for item in duplicate_groups
            if any(unit.get("overlap_type") == "STRUCTURED_IDENTITY" for unit in units if unit["unit_id"] in item["unit_ids"])
        ],
        "model_calls": 0,
    }


audit_mandatory_payload = audit_mandatory_planning_payload
breakdown_mandatory_planning_payload = audit_mandatory_planning_payload
audit_mandatory_payload_budget = audit_mandatory_planning_payload


def _canonical_mandatory_model_payload(payload, core):
    """Replace repeated authority prose with the core's compact projection."""
    value = copy.deepcopy(payload if isinstance(payload, dict) else {})
    projection = copy.deepcopy((core or {}).get("model_projection", {}))
    # These fields are represented once in current_project_state/current-vs-
    # desired.  Full records remain in the core and the VerifiedPlanningContext.
    for field in (
        "current_authority", "confirmed_conflicts", "dnt", "planning_provenance",
        "current_vs_desired", "prohibitions", "interfaces",
    ):
        value.pop(field, None)
    value["mandatory_core"] = projection
    # Preserve a compatibility key without repeating its meanings.  The
    # actual statements are in mandatory_core.current_project_state.
    value["preservation_constraints"] = [
        {"id": item.get("id")}
        for item in projection.get("current_project_state", {}).get("preservation", [])
        if isinstance(item, dict) and item.get("id")
    ]
    # Keep the historical top-level conflict key for deterministic validators;
    # the conflict meaning itself is emitted only in the canonical current
    # state.  The top-level list is an ID-only compatibility reference.
    value["confirmed_conflicts"] = copy.deepcopy(
        [
            {"id": item.get("id")}
            for item in projection.get("current_project_state", {}).get("confirmed_conflicts", [])
            if isinstance(item, dict) and item.get("id")
        ]
    )
    requirements = list(value.get("requirements", []) or [])
    requirement_by_text = {
        _core_normalize_text(_core_text(item, 900)): str(item.get("requirement_id") or item.get("id"))
        for item in requirements
        if isinstance(item, dict) and (item.get("requirement_id") or item.get("id"))
    }
    task_goal = value.get("task_goal")
    task_goal_text = task_goal.get("text") if isinstance(task_goal, dict) else task_goal
    matching_requirement = requirement_by_text.get(_core_normalize_text(task_goal_text))
    if matching_requirement:
        # ``requirements`` is the one model-facing home for the full current
        # user requirement.  Keep the historical task_goal field as a bounded
        # reference so the requirement prose is not rendered twice.
        value["task_goal"] = {"requirement_id": matching_requirement}
    value["planning_core_ref"] = {
        "artifact_type": CANONICAL_MANDATORY_PLANNING_CORE_TYPE,
        "version": CANONICAL_MANDATORY_PLANNING_CORE_VERSION,
        "hash": (core or {}).get("mandatory_core_hash"),
    }
    return value


def audit_current_vs_desired_representation(payload):
    """Validate the explicit structured current/desired boundary.

    This audit intentionally examines declared fields only.  It never infers
    current state or desired state from substrings in prose.
    """
    value = payload if isinstance(payload, dict) else {}
    projection = value.get("mandatory_core")
    if not isinstance(projection, dict):
        projection = value.get("model_projection")
    if isinstance(projection, dict):
        boundary = projection.get("current_vs_desired")
        state = projection.get("current_project_state")
        desired = projection.get("desired_user_change")
        if (
            isinstance(boundary, dict)
            and isinstance(boundary.get("desired"), list)
            and isinstance(boundary.get("current"), list)
            and isinstance(state, dict)
            and isinstance(desired, list)
        ):
            return {
                "valid": True,
                "source": "CANONICAL_MANDATORY_CORE",
                "desired_ids": list(boundary.get("desired", [])),
                "current_ids": list(boundary.get("current", [])),
                "desired_items": len(desired),
                "current_state_sections": sorted(str(key) for key in state),
            }
    boundary = value.get("current_vs_desired")
    if isinstance(boundary, dict):
        required = ("desired_requirement_ids", "current_authority_ids", "current_evidence_ids")
        if all(isinstance(boundary.get(key), list) for key in required):
            return {
                "valid": True,
                "source": "LEGACY_STRUCTURED_BOUNDARY",
                "desired_ids": list(boundary.get("desired_requirement_ids", [])),
                "current_ids": list(boundary.get("current_authority_ids", [])),
                "desired_items": len(boundary.get("desired_requirement_ids", [])),
                "current_state_sections": ["current_authority", "current_evidence"],
            }
    return {
        "valid": False,
        "source": None,
        "desired_ids": [],
        "current_ids": [],
        "desired_items": 0,
        "current_state_sections": [],
        "error": "explicit structured current_vs_desired representation is missing",
    }


audit_current_vs_desired = audit_current_vs_desired_representation


def _role_core_source(payload, nested_key=None):
    """Select structured mandatory inputs for a role's canonical core."""
    value = payload if isinstance(payload, dict) else {}
    if nested_key and isinstance(value.get(nested_key), dict):
        source = copy.deepcopy(value.get(nested_key))
    else:
        source = copy.deepcopy(value)
    candidate = value.get("candidate_impact_map")
    if not source.get("task_goal") and isinstance(candidate, dict) and candidate.get("task_goal"):
        source["task_goal"] = copy.deepcopy(candidate.get("task_goal"))
    return source


def _canonical_role_model_payload(payload, core, nested_key=None):
    """Place one canonical projection in a role packet without nested copies."""
    value = payload if isinstance(payload, dict) else {}
    if not nested_key:
        return _canonical_mandatory_model_payload(value, core)
    result = copy.deepcopy(value)
    nested = result.get(nested_key)
    if isinstance(nested, dict):
        nested = _canonical_mandatory_model_payload(nested, core)
        nested.pop("mandatory_core", None)
        nested.pop("planning_core_ref", None)
        result[nested_key] = nested
    result["mandatory_core"] = copy.deepcopy((core or {}).get("model_projection", {}))
    result["planning_core_ref"] = {
        "artifact_type": CANONICAL_MANDATORY_PLANNING_CORE_TYPE,
        "version": CANONICAL_MANDATORY_PLANNING_CORE_VERSION,
        "hash": (core or {}).get("mandatory_core_hash"),
    }
    requirements = result.get("requirements")
    if not isinstance(requirements, list) and isinstance(result.get("planning_packet"), dict):
        requirements = result["planning_packet"].get("requirements")
    requirement_by_text = {
        _core_normalize_text(_core_text(item, 900)): str(item.get("requirement_id") or item.get("id"))
        for item in list(requirements or [])
        if isinstance(item, dict) and (item.get("requirement_id") or item.get("id"))
    }
    candidate = result.get("candidate_impact_map")
    if isinstance(candidate, dict) and candidate.get("task_goal"):
        candidate_goal = candidate.get("task_goal")
        candidate_goal_text = (
            candidate_goal.get("text") if isinstance(candidate_goal, dict) else candidate_goal
        )
        matching_requirement = requirement_by_text.get(_core_normalize_text(candidate_goal_text))
        if matching_requirement:
            candidate["task_goal"] = {"requirement_id": matching_requirement}
    return result


def _planner_authority_projection(task_brain, requirements=None, verified_planning_context=None):
    """Project current authority as compact references, not a second artifact."""
    brain = task_brain if isinstance(task_brain, dict) else {}
    source = verified_planning_context if isinstance(verified_planning_context, dict) else brain
    requirement_texts = {
        _compact(item.get("text"), 520).casefold()
        for item in active_requirements(requirements)
        if isinstance(item, dict)
    }
    fields = (
        ("current_authority", "CURRENT_AUTHORITY"),
        ("current_durable_authority", "CURRENT_AUTHORITY"),
        ("current_verified_facts", "CURRENT_VERIFIED"),
        ("current_owners", "CURRENT_OWNER"),
        ("current_state_ownership", "CURRENT_STATE_OWNER"),
        ("current_interfaces", "CURRENT_INTERFACE"),
        ("interfaces", "REQUIRED_INTERFACE"),
    )
    result = []
    by_key = {}
    for field, authority_type in fields:
        for item in list(source.get(field, []) or [])[:32]:
            if not isinstance(item, dict):
                continue
            text = _planner_record_text(item)
            refs = _planner_source_ids(item)
            path = _normal_path(item.get("path"))
            symbol = _compact(item.get("symbol"), 180)
            relation = _core_relation(item)
            # A requirement record is already the mandatory user statement;
            # retain its source identity only when it also carries a durable
            # authority/evidence identity.
            if not text and not refs and not path and not symbol:
                continue
            # A durable fact commonly appears in both ``current_authority``
            # and ``current_verified_facts``.  Keep the distinct source refs
            # and authority classes internally, but render one bounded
            # model-facing statement for the shared semantic obligation.
            # Exact normalized prose/location is the fallback identity.  A
            # declared semantic ID or structured relation always wins, so
            # distinct authority relations cannot be hidden by a shared path.
            key = (
                _core_explicit_identity(item)
                or f"EXACT:{text.casefold()}:{path.casefold()}:{symbol.casefold()}"
            )
            if key in by_key:
                existing = by_key[key]
                existing["source_ids"] = _bounded_ids(
                    list(existing.get("source_ids", [])) + refs, 12,
                )
                authority_types = list(existing.get("authority_types", []))
                if not authority_types and existing.get("authority_type"):
                    authority_types.append(existing["authority_type"])
                if authority_type not in authority_types:
                    authority_types.append(authority_type)
                existing["authority_types"] = authority_types
                continue
            entry = {
                "authority_type": authority_type,
                "authority_types": [authority_type],
                "source_ids": refs,
                "text": text,
                "path": path,
                "symbol": symbol,
            }
            if relation:
                entry["structured_relation"] = relation
            for structured_key in ("category", "field"):
                if item.get(structured_key):
                    entry[structured_key] = str(item.get(structured_key))
            matching_requirement_ids = [
                item.get("requirement_id") for item in active_requirements(requirements)
                if _compact(item.get("text"), 520).casefold() == text.casefold()
            ]
            if text.casefold() in requirement_texts:
                # The full user statement is already mandatory in
                # ``requirements``.  Preserve the durable/interface source
                # identities and authority class, but render one bounded
                # semantic statement instead of repeating identical prose.
                refs = list(dict.fromkeys(refs + [item for item in matching_requirement_ids if item]))
                entry["source_ids"] = refs
                entry["requirement_ids"] = [item for item in matching_requirement_ids if item]
                entry.pop("text", None)
            if not entry.get("source_ids") and not entry.get("requirement_ids"):
                continue
            entry = {key: value for key, value in entry.items() if value not in ("", [], None)}
            if entry.get("authority_types") == [entry.get("authority_type")]:
                entry.pop("authority_types", None)
            by_key[key] = entry
            result.append(entry)
    return result[:32]


def _planner_conflict_projection(task_brain, verified_planning_context=None):
    source = (
        verified_planning_context if isinstance(verified_planning_context, dict)
        else task_brain if isinstance(task_brain, dict) else {}
    )
    result = []
    for item in list(source.get("confirmed_conflicts", []) or [])[:16]:
        if not isinstance(item, dict):
            continue
        relation = item.get("authority_relation") or item.get("repository_relation")
        entry = {
            "conflict_id": item.get("conflict_id"),
            "kind": item.get("kind") or item.get("drift_classification"),
            "drift_classification": item.get("drift_classification", "CONFIRMED_DRIFT"),
            "authority_record_id": item.get("authority_record_id"),
            "authority_fact": _compact(item.get("authority_fact") or item.get("text"), 320),
            "authority_fact_hash": item.get("authority_fact_hash") or item.get("fact_hash"),
            "repository_evidence_ids": _bounded_ids(
                item.get("repository_evidence_ids") or item.get("evidence_ids"), 8,
            ),
            "repository_relation": copy.deepcopy(relation) if isinstance(relation, dict) else None,
        }
        entry = {key: value for key, value in entry.items() if value not in (None, "", [], {})}
        if entry.get("conflict_id") or entry.get("authority_fact"):
            result.append(entry)
    return result


def _planner_stale_projection(task_brain, verified_planning_context=None):
    source = (
        verified_planning_context if isinstance(verified_planning_context, dict)
        else task_brain if isinstance(task_brain, dict) else {}
    )
    result = []
    for item in list(source.get("stale_evidence_warnings", []) or [])[:16]:
        if not isinstance(item, dict):
            continue
        value = {
            "record_id": item.get("record_id"),
            "fact_hash": item.get("fact_hash"),
            "classification": "STALE_WARNING",
            "warning": _compact(item.get("fact_summary") or item.get("stale_reason") or item.get("text"), 320),
            "evidence_refs": _bounded_ids(
                item.get("evidence_refs") or item.get("evidence_ids"), 8,
            ),
        }
        result.append({key: value for key, value in value.items() if value not in (None, "", [], {})})
    return result


def _planner_not_evaluable_projection(task_brain, verified_planning_context=None):
    source = (
        verified_planning_context if isinstance(verified_planning_context, dict)
        else task_brain if isinstance(task_brain, dict) else {}
    )
    audits = list(source.get("not_evaluable_audit", []) or [])
    if not audits:
        audits = [
            item for item in list(source.get("authority_drift_audit", []) or [])
            if isinstance(item, dict) and str(item.get("classification", "")).upper() == "NOT_EVALUABLE"
        ]
    result = []
    for item in audits[:16]:
        if not isinstance(item, dict):
            continue
        value = {
            "authority_record_id": item.get("authority_record_id"),
            "evidence_refs": _bounded_ids(item.get("evidence_refs"), 8),
            "classification": "NOT_EVALUABLE",
            "reason_code": _compact(item.get("reason_code"), 120),
        }
        result.append({key: value for key, value in value.items() if value not in (None, "", [], {})})
    return result


def _planner_source_metadata(task_brain, verified_planning_context=None):
    source = (
        verified_planning_context if isinstance(verified_planning_context, dict)
        else task_brain if isinstance(task_brain, dict) else {}
    )
    return {
        "planning_mode": source.get("planning_mode"),
        "source_planning_context_hash": source.get("planning_context_hash")
        or source.get("verified_planning_context_hash"),
        "source_task_brain_hash": source.get("source_task_brain_hash")
        or source.get("task_brain_hash"),
        "source_reentry_hash": source.get("source_reentry_hash")
        or source.get("reentry_hash"),
    }


def _planner_preservation_projection(task_brain, requirements, verified_planning_context=None):
    brain = task_brain if isinstance(task_brain, dict) else {}
    result = []
    source = verified_planning_context if isinstance(verified_planning_context, dict) else brain
    requirement_ids_by_text = {}
    for requirement in active_requirements(requirements):
        text = _compact(requirement.get("text"), 520)
        if text:
            requirement_ids_by_text.setdefault(text.casefold(), []).append(
                requirement.get("requirement_id")
            )
    source_items = [
        (item, False) for item in list(brain.get("preservation_constraints", []) or [])
    ]
    source_items.extend(
        (item, True) for item in list(source.get("prohibitions", []) or [])
    )
    source_items.extend(
        (item, True) for item in list(source.get("dnt", []) or [])
    )
    seen = {}
    for item, forced_dnt in source_items[:16]:
        if isinstance(item, dict):
            value = {
                "text": _compact(item.get("text") or item.get("fact"), 520),
                "requirement_ids": _bounded_ids(item.get("requirement_ids"), 8),
                "evidence_ids": _bounded_ids(
                    item.get("evidence_ids") or item.get("evidence_refs"), 8,
                ),
                "provenance": item.get("provenance", USER_STATED),
            }
        else:
            value = {"text": _compact(item, 520), "requirement_ids": [], "evidence_ids": [],
                     "provenance": USER_STATED}
        if value["text"]:
            source_text = value["text"]
            text_key = source_text.casefold()
            matching_requirement_ids = [
                item for item in requirement_ids_by_text.get(text_key, []) if item
            ]
            if matching_requirement_ids:
                value["requirement_ids"] = _bounded_ids(
                    list(value.get("requirement_ids", [])) + matching_requirement_ids, 8,
                )
                # The full user statement remains in ``requirements``.  The
                # preservation projection keeps its provenance and source
                # IDs, but does not render that same sentence a second time.
                value.pop("text", None)
            if text_key in seen:
                seen[text_key]["requirement_ids"] = _bounded_ids(
                    list(seen[text_key].get("requirement_ids", [])) + value["requirement_ids"], 8,
                )
                seen[text_key]["evidence_ids"] = _bounded_ids(
                    list(seen[text_key].get("evidence_ids", [])) + value["evidence_ids"], 8,
                )
                if forced_dnt:
                    seen[text_key]["constraint_type"] = "DNT"
            else:
                if _PROHIBITION_RE.search(source_text) or forced_dnt:
                    value["constraint_type"] = "DNT"
                seen[text_key] = value
                result.append(value)
    existing_text = set(seen)
    for requirement in active_requirements(requirements):
        text = requirement.get("text", "")
        if (_PRESERVE_RE.search(text) or _PROHIBITION_RE.search(text)) and text.casefold() not in existing_text:
            entry = {
                "text": _compact(text, 520),
                "requirement_ids": [requirement["requirement_id"]],
                "evidence_ids": [],
                "provenance": requirement.get("provenance", USER_STATED),
            }
            if _PROHIBITION_RE.search(text):
                entry["constraint_type"] = "DNT"
            result.append(entry)
    return result[:16]


def _planner_surface_packet(surface):
    """Serialize one complete canonical surface in a compact form."""
    return {
        "surface_id": str(surface.get("surface_id")),
        "kind": surface.get("kind"),
        "role": surface.get("role"),
        "path": _normal_path(surface.get("path")),
        "symbol": str(surface.get("symbol") or ""),
        "verified_fact": _compact(surface.get("verified_fact") or surface.get("fact"), 360),
        "evidence_ids": _bounded_ids(surface.get("evidence_ids"), MAX_SURFACE_EVIDENCE_IDS),
        "owner_surface_id": surface.get("owner_surface_id"),
    }


def _planner_seed_packet(seed):
    # The selected surface is the authoritative carrier for the verified
    # fact and identity.  A seed repeats only the binding and reference data
    # that the planner must return; duplicating path/symbol/fact fields in
    # both records made the mandatory projection unnecessarily large.
    value = {
        "impact_id": normalize_impact_id(seed.get("impact_id")),
        "surface_id": str(seed.get("surface_id") or ""),
        "requirement_ids": _bounded_ids(seed.get("requirement_ids"), MAX_REQUIREMENT_REFS_PER_IMPACT),
        "evidence_ids": _bounded_ids(seed.get("canonical_evidence_ids") or seed.get("evidence_ids"), MAX_SURFACE_EVIDENCE_IDS),
        "canonical_path": _normal_path(seed.get("canonical_path") or seed.get("verified_path")),
        "canonical_symbol": str(seed.get("canonical_symbol") or seed.get("verified_symbol") or ""),
        "eligible": bool(seed.get("eligible", True)),
    }
    relationships = list(seed.get("requirement_relationships", []) or [])[:4]
    if relationships:
        value["requirement_relationships"] = [{
            "requirement_id": item.get("requirement_id"),
            "companion_requirement_id": item.get("companion_requirement_id"),
            "relationship": "COMPANION",
        } for item in relationships]
    return value


def _trim_planner_optional_payload(packet, max_chars):
    """Trim only optional prose/facts; never trim planning authority."""
    value = copy.deepcopy(packet)

    def size():
        return len(_compact_json(value))

    while size() > max_chars:
        project = value.get("project_context")
        if isinstance(project, list) and project:
            project.pop()
            continue
        task_facts = value.get("task_facts")
        removed = False
        if isinstance(task_facts, dict):
            for field in (
                "known_non_goals", "acceptance_conditions", "relevant_dependencies",
                "current_interfaces", "current_state_ownership", "current_owners",
                "relevant_tests", "user_confirmed_decisions",
            ):
                values = task_facts.get(field)
                if isinstance(values, list) and values:
                    values.pop()
                    removed = True
                    break
                if isinstance(values, list) and not values:
                    task_facts.pop(field, None)
            if not removed and task_facts:
                value["task_facts"] = {}
                removed = True
        if removed:
            continue
        evidence = value.get("accepted_repository_evidence")
        if isinstance(evidence, list) and evidence:
            evidence.pop()
            continue
        break
    return value


def _planning_packet_payload(task_brain, requirements, evidence, surfaces, seeds,
                             project_invariants=None, max_chars=MAX_PLANNER_CONTEXT_CHARS,
                             verified_planning_context=None,
                             include_role_authority=True):
    brain = task_brain if isinstance(task_brain, dict) else {}
    goal = brain.get("task_goal", "")
    if isinstance(goal, dict):
        goal = goal.get("text", "")
    selected_ids = [str(item.get("surface_id")) for item in surfaces]
    preservation = _planner_preservation_projection(
        task_brain, requirements, verified_planning_context=verified_planning_context,
    )
    authority = _planner_authority_projection(
        task_brain, requirements, verified_planning_context=verified_planning_context,
    )
    conflicts = _planner_conflict_projection(
        task_brain, verified_planning_context=verified_planning_context,
    )
    stale_warnings = _planner_stale_projection(
        task_brain, verified_planning_context=verified_planning_context,
    )
    not_evaluable = _planner_not_evaluable_projection(
        task_brain, verified_planning_context=verified_planning_context,
    )
    source_metadata = _planner_source_metadata(
        task_brain, verified_planning_context=verified_planning_context,
    )
    desired_requirement_ids = [
        str(item.get("requirement_id")) for item in active_requirements(requirements)
        if item.get("requirement_id")
    ]
    current_evidence_ids = _bounded_ids(
        [item.get("evidence_id") for item in bounded_evidence(evidence, MAX_CANONICAL_SURFACES * 2)],
        MAX_CANONICAL_SURFACES * 2,
    )
    authority_source_ids = _bounded_ids(
        [ref for item in authority for ref in item.get("source_ids", [])], 32,
    )
    dnt_refs = []
    for index, item in enumerate(preservation, 1):
        # The complete DNT statement is already present in the mandatory
        # preservation projection.  Repeat only its compact refs when they
        # add identity that is not otherwise available; avoid rendering the
        # same prohibition prose twice.
        if item.get("constraint_type") == "DNT" and (
            item.get("requirement_ids") or item.get("evidence_ids")
        ):
            dnt_refs.append({
                "constraint_id": f"DNT-{index:03d}",
                "requirement_ids": list(item.get("requirement_ids", [])),
                "evidence_ids": list(item.get("evidence_ids", [])),
            })
    preservation_texts = {
        str(item.get("text", "")).casefold()
        for item in preservation if isinstance(item, dict) and item.get("text")
    }
    for item in authority:
        # Distinct authority source IDs remain.  The shared statement is
        # rendered once in preservation when it is semantically identical.
        if (
            isinstance(item, dict)
            and item.get("text")
            and str(item.get("text")).casefold() in preservation_texts
            and item.get("source_ids")
        ):
            item.pop("text", None)
    planning_provenance = {
        key: value for key, value in source_metadata.items()
        if value not in (None, "", [], {})
    }
    packet = {
        "version": 1,
        "task_goal": _compact(goal, 1000),
        "requirements": _planner_requirement_projection(requirements),
        "surfaces": [_planner_surface_packet(item) for item in surfaces],
        "impact_seeds": [_planner_seed_packet(item) for item in seeds],
        "preservation_constraints": preservation,
        "planning_rules": [
            # The role envelope carries the full prose instructions.  These
            # stable labels retain the machine-checkable rule set without
            # repeating that prose inside the bounded payload.
            "KNOWN_IMPACT_SLOTS_ONLY",
            "VALID_REQUIREMENT_IDS_ONLY",
            "REUSE_CANONICAL_INTERFACES",
            "PRESERVE_VERIFIED_STATE_UNLESS_PROVEN",
            "JUSTIFY_NEW_SURFACE_PROPOSALS",
        ],
        "accepted_repository_evidence": _planner_evidence_projection(
            evidence, selected_surface_ids=selected_ids, registry={"surfaces": surfaces},
        ),
        "task_facts": _planner_task_fact_projection(task_brain),
        "project_context": _bounded_strings(project_invariants, 8, 360),
        "bounds": {
            "max_impact_entries": MAX_IMPACT_ENTRIES,
            "max_requirement_refs_per_impact": MAX_REQUIREMENT_REFS_PER_IMPACT,
            "max_evidence_refs_per_impact": MAX_EVIDENCE_REFS_PER_IMPACT,
            "max_canonical_surfaces": MAX_CANONICAL_SURFACES,
            "max_impact_seeds": MAX_IMPACT_SEEDS,
            "max_serialized_chars": max_chars,
        },
    }
    if include_role_authority:
        # These are compact authority references.  The complete V24 records
        # remain in VerifiedPlanningContext; the model projection does not
        # replace or mutate that structured artifact.
        packet.update({
            "current_authority": authority,
            "confirmed_conflicts": conflicts,
            "dnt": dnt_refs,
            "planning_provenance": planning_provenance,
            "current_vs_desired": {
                "desired_requirement_ids": desired_requirement_ids,
                "current_authority_ids": authority_source_ids,
                "current_evidence_ids": current_evidence_ids,
            },
            "stale_evidence_warnings": stale_warnings,
            "not_evaluable_audit": not_evaluable,
        })
    return packet


def _planner_optional_items(payload):
    """Return complete optional model-facing units in deterministic order."""
    value = payload if isinstance(payload, dict) else {}
    result = []
    order = 0

    def add(category, priority, path, item, index, source_ids=None, semantic_key=None):
        nonlocal order
        order += 1
        result.append({
            "item_id": f"{category.upper()}-{index + 1:03d}",
            "category": category,
            "priority": priority,
            "path": tuple(path),
            "index": index,
            "value": copy.deepcopy(item),
            "source_ids": list(source_ids or []),
            "semantic_key": semantic_key,
            "_order": order,
        })

    for index, item in enumerate(list(value.get("accepted_repository_evidence", []) or [])):
        if isinstance(item, dict):
            add(
                "repository_evidence", 70, ("accepted_repository_evidence",), item, index,
                source_ids=[item.get("evidence_id")] if item.get("evidence_id") else [],
                semantic_key=str(item.get("evidence_id") or ""),
            )
    task_facts = value.get("task_facts") if isinstance(value.get("task_facts"), dict) else {}
    task_priority = {
        "user_confirmed_decisions": 90,
        "current_owners": 60,
        "current_state_ownership": 60,
        "current_interfaces": 60,
        "relevant_tests": 55,
        "relevant_dependencies": 45,
        "acceptance_conditions": 35,
        "known_non_goals": 25,
    }
    for field, priority in task_priority.items():
        for index, item in enumerate(list(task_facts.get(field, []) or [])):
            if isinstance(item, dict):
                add(
                    f"task_facts_{field}", priority, ("task_facts", field), item, index,
                    source_ids=_planner_source_ids(item),
                    semantic_key=_planner_record_text(item).casefold(),
                )
    for index, item in enumerate(list(value.get("stale_evidence_warnings", []) or [])):
        if isinstance(item, dict):
            add(
                "stale_warning", 30, ("stale_evidence_warnings",), item, index,
                source_ids=_planner_source_ids(item),
                semantic_key=str(item.get("record_id") or item.get("fact_hash") or ""),
            )
    for index, item in enumerate(list(value.get("not_evaluable_audit", []) or [])):
        if isinstance(item, dict):
            add(
                "not_evaluable_audit", 10, ("not_evaluable_audit",), item, index,
                source_ids=_planner_source_ids(item),
                semantic_key=str(item.get("authority_record_id") or index),
            )
    for index, item in enumerate(list(value.get("project_context", []) or [])):
        add(
            "project_context", 20, ("project_context",), item, index,
            semantic_key=str(item).casefold(),
        )
    return result


def _planner_mandatory_payload(payload, optional_items):
    """Remove optional containers while retaining their fixed semantic schema."""
    value = copy.deepcopy(payload if isinstance(payload, dict) else {})
    for field in (
        "accepted_repository_evidence", "task_facts", "project_context",
        "stale_evidence_warnings", "not_evaluable_audit",
    ):
        value.pop(field, None)
    return value


def build_canonical_planning_packet(task_brain, requirements, evidence,
                                    project_invariants=None, surface_registry=None,
                                    max_chars=None,
                                    max_surfaces=MAX_CANONICAL_SURFACES,
                                    role="ImpactPlanner", render=None, base_render=None,
                                    verified_planning_context=None):
    """Build and validate the complete ImpactPlanner-specific packet.

    The generic context projection is intentionally not used here.  Required
    requirements, selected canonical surfaces, seeds, and preservation
    constraints are core packet authority; only optional evidence/prose units
    can be trimmed.  When ``render`` is supplied, its exact final string is
    the authoritative budget subject.  If the mandatory projection cannot
    fit, the result is explicitly incomplete and callers must not invoke the
    planner.
    """
    max_chars = MAX_PLANNER_CONTEXT_CHARS if max_chars is None else max_chars
    max_chars = max(1, int(max_chars))
    # Direct Stage 3 callers historically received a compact JSON payload
    # bound by ``max_chars``.  Keep that compatibility projection unchanged;
    # the production role path opts into the richer authority projection and
    # supplies the exact role renderer below.
    include_role_authority = (
        isinstance(verified_planning_context, dict)
        or any(
            isinstance(task_brain, dict) and task_brain.get(field)
            for field in (
                "current_authority", "confirmed_conflicts", "stale_evidence_warnings",
                "not_evaluable_audit", "dnt", "prohibitions",
            )
        )
    )
    registry = surface_registry or build_canonical_surface_registry(task_brain, evidence)
    registry_validation = validate_canonical_surface_registry(registry, evidence)
    selection = select_task_relevant_surfaces(
        task_brain, requirements, evidence, registry=registry, max_surfaces=max_surfaces,
    )
    selected = list(selection.get("selected", []))
    required_ids = set(selection.get("required_surface_ids", []))
    selected_ids = [str(item.get("surface_id")) for item in selected]
    errors = list(registry_validation.get("errors", [])) if not registry_validation.get("valid") else []
    if selection.get("missing_required_surface_ids"):
        errors.append("required canonical surfaces exceed the deterministic surface bound")

    scores = selection.get("scores", {})

    def assemble(surface_values):
        surface_values = list(surface_values)
        ids = [str(item.get("surface_id")) for item in surface_values]
        seeds = build_impact_seeds(
            task_brain, requirements, evidence, registry=registry,
            selected_surface_ids=ids,
        )
        seed_validation = validate_impact_seeds(seeds, registry, selected_surface_ids=ids)
        payload = _planning_packet_payload(
            task_brain, requirements, evidence, surface_values, seeds,
            project_invariants=project_invariants, max_chars=max_chars,
            verified_planning_context=verified_planning_context,
            include_role_authority=include_role_authority,
        )
        # V24.2 keeps this complete pre-normalization payload local to the
        # compiler.  It is the audit source; it is never sent to the model.
        raw_mandatory_payload = _planner_mandatory_payload(payload, [])
        raw_mandatory_value = copy.deepcopy(raw_mandatory_payload)
        raw_mandatory_value["packet_complete"] = True
        mandatory_payload_audit = audit_mandatory_planning_payload(raw_mandatory_value)
        source_metadata = _planner_source_metadata(
            task_brain, verified_planning_context=verified_planning_context,
        )
        mandatory_core = build_canonical_mandatory_planning_core(
            raw_mandatory_payload,
            project_id=(verified_planning_context or {}).get("project_id")
            if isinstance(verified_planning_context, dict) else None,
            task_id=(verified_planning_context or {}).get("task_id")
            if isinstance(verified_planning_context, dict) else None,
            source_planning_context_hash=source_metadata.get("source_planning_context_hash"),
            source_task_brain_hash=source_metadata.get("source_task_brain_hash"),
            source_reentry_hash=source_metadata.get("source_reentry_hash"),
        )
        payload = _canonical_mandatory_model_payload(payload, mandatory_core)
        optional_items = _planner_optional_items(payload)
        mandatory_payload = _planner_mandatory_payload(payload, optional_items)
        normalized_mandatory_value = copy.deepcopy(mandatory_payload)
        normalized_mandatory_value["packet_complete"] = True
        normalized_mandatory_chars = len(_compact_json(normalized_mandatory_value))
        mandatory_ids = ["TASK_GOAL"]
        mandatory_ids.extend(
            f"REQUIREMENT-{item.get('requirement_id')}"
            for item in _planner_requirement_projection(requirements)
            if item.get("requirement_id")
        )
        mandatory_ids.extend(str(item.get("surface_id")) for item in surface_values)
        mandatory_ids.extend(
            str(item.get("impact_id")) for item in seeds if item.get("impact_id")
        )
        mandatory_ids.extend(
            f"PRESERVATION-{index:03d}"
            for index, item in enumerate(payload.get("preservation_constraints", []), 1)
            if isinstance(item, dict) and item.get("text")
        )
        mandatory_ids.extend(
            str(item.get("conflict_id"))
            for item in raw_mandatory_payload.get("confirmed_conflicts", [])
            if isinstance(item, dict) and item.get("conflict_id")
        )
        mandatory_ids.extend(
            str(item.get("canonical_semantic_id"))
            for item in mandatory_core.get("mandatory_semantic_coverage", [])
            if isinstance(item, dict)
            and item.get("model_semantic_required")
            and item.get("canonical_semantic_id")
        )
        if include_role_authority:
            mandatory_ids.extend(["CANONICAL_MANDATORY_CORE", "CURRENT_VS_DESIRED"])
        mandatory_ids.append("PLANNING_RULES")

        def payload_factory(selected_items, marker=True):
            value = _role_payload_factory(mandatory_payload, selected_items)
            value["packet_complete"] = bool(marker)
            return value

        role_packet = build_planning_role_packet(
            role, mandatory_payload, optional_items,
            hard_limit=max_chars, render=render, base_render=base_render,
            source_planning_context_hash=(
                _planner_source_metadata(task_brain, verified_planning_context)
                .get("source_planning_context_hash")
            ),
            mandatory_items=mandatory_ids,
            payload_factory=lambda selected: payload_factory(selected, marker=True),
            planning_core_hash=mandatory_core.get("mandatory_core_hash"),
            mandatory_payload_audit=mandatory_payload_audit,
            mandatory_semantic_coverage=mandatory_core.get("mandatory_semantic_coverage", []),
            mandatory_model_chars_before_normalization=mandatory_payload_audit.get("payload_chars"),
            mandatory_model_chars_after_normalization=normalized_mandatory_chars,
            mandatory_core_metrics=mandatory_core.get("metrics"),
        )
        # Structural errors must be reflected in the exact model packet too;
        # the marker is never appended after the packet was audited.
        return (
            role_packet.get("payload", {}), seeds, seed_validation,
            role_packet.get("rendered_chars", 0), role_packet,
            optional_items, mandatory_payload, mandatory_ids, mandatory_core,
            mandatory_payload_audit, normalized_mandatory_chars,
        )

    (
        payload, seeds, seed_validation, packet_chars, role_packet,
        optional_items, mandatory_payload, mandatory_ids, mandatory_core,
        mandatory_payload_audit, normalized_mandatory_chars,
    ) = assemble(selected)
    # Optional relevant surfaces are dropped before serialization only when
    # the complete candidate set cannot fit.  Required surfaces are never
    # silently dropped.
    optional = [
        item for item in selected
        if str(item.get("surface_id")) not in required_ids
    ]
    optional.sort(key=lambda item: (
        scores.get(str(item.get("surface_id")), {}).get("score", 0),
        selected.index(item),
    ))
    while not role_packet.get("packet_complete") and optional:
        remove = optional.pop(0)
        selected = [item for item in selected if item is not remove]
        (
            payload, seeds, seed_validation, packet_chars, role_packet,
            optional_items, mandatory_payload, mandatory_ids, mandatory_core,
            mandatory_payload_audit, normalized_mandatory_chars,
        ) = assemble(selected)
    selected_ids = [str(item.get("surface_id")) for item in selected]
    serialized_ids = [str(item.get("surface_id")) for item in payload.get("surfaces", [])]
    dropped_ids = [
        str(item.get("surface_id")) for item in list(registry.get("surfaces", []) or [])
        if str(item.get("surface_id")) not in selected_ids
    ]
    errors = list(registry_validation.get("errors", [])) if not registry_validation.get("valid") else []
    if selection.get("missing_required_surface_ids"):
        errors.append("required canonical surfaces exceed the deterministic surface bound")
    if packet_chars > max_chars:
        errors.append(
            f"exact {role} planning packet exceeds {max_chars} rendered characters"
        )
    if not seed_validation.get("valid"):
        errors.extend(seed_validation.get("errors", []))
    if set(selected_ids) != set(serialized_ids):
        errors.append("selected canonical surfaces were not serialized completely")
    if serialized_ids and not seeds:
        errors.append("planner packet has no surface-bound impact seeds")
    if len(seeds) != len(serialized_ids):
        errors.append("surface-bound impact seeds were not serialized completely")
    if role_packet.get("status") != "READY":
        errors.extend(role_packet.get("errors", []))
    complete = bool(role_packet.get("packet_complete")) and not errors
    if payload.get("packet_complete") is not complete:
        # Re-render the same semantic units with the final completeness marker
        # before publishing any audit or provider-facing string.
        final_optional_ids = set(role_packet.get("optional_items_selected", []))
        selected_optional = [
            item for item in optional_items
            if str(item.get("item_id")) in final_optional_ids
        ]
        value = _role_payload_factory(mandatory_payload, selected_optional)
        value["packet_complete"] = complete
        role_packet = build_planning_role_packet(
            role, mandatory_payload, optional_items,
            hard_limit=max_chars, render=render, base_render=base_render,
            source_planning_context_hash=(
                _planner_source_metadata(task_brain, verified_planning_context)
                .get("source_planning_context_hash")
            ),
            mandatory_items=mandatory_ids,
            payload_factory=lambda chosen: (
                dict(_role_payload_factory(mandatory_payload, chosen), packet_complete=complete)
            ),
            packet_complete_override=complete,
            planning_core_hash=mandatory_core.get("mandatory_core_hash"),
            mandatory_payload_audit=mandatory_payload_audit,
            mandatory_semantic_coverage=mandatory_core.get("mandatory_semantic_coverage", []),
            mandatory_model_chars_before_normalization=mandatory_payload_audit.get("payload_chars"),
            mandatory_model_chars_after_normalization=normalized_mandatory_chars,
            mandatory_core_metrics=mandatory_core.get("metrics"),
        )
        payload = role_packet.get("payload", value)
        packet_chars = role_packet.get("rendered_chars", 0)
        complete = bool(role_packet.get("packet_complete")) and not errors
    else:
        packet_chars = role_packet.get("rendered_chars", packet_chars)
    selection = copy.deepcopy(selection)
    selection.update({
        "selected": copy.deepcopy(selected),
        "selected_surface_ids": list(selected_ids),
        "dropped_surface_ids": list(dropped_ids),
        "missing_required_surface_ids": sorted(
            set(selection.get("required_surface_ids", [])) - set(selected_ids)
        ),
    })
    observability = {
        "selected_surface_ids": selected_ids,
        "serialized_surface_ids": serialized_ids,
        "dropped_surface_ids": dropped_ids,
        "impact_seed_ids": [normalize_impact_id(item.get("impact_id")) for item in seeds],
        "packet_chars": packet_chars,
        "payload_chars": len(_compact_json(payload)),
        "estimated_tokens": _estimated_tokens(role_packet.get("rendered_packet", _compact_json(payload))),
        "packet_complete": complete,
        "mandatory_core_hash": mandatory_core.get("mandatory_core_hash"),
        "mandatory_model_chars_before_normalization": mandatory_payload_audit.get("payload_chars"),
        "mandatory_model_chars_after_normalization": normalized_mandatory_chars,
        "mandatory_semantic_coverage": mandatory_core.get("mandatory_semantic_coverage", []),
        "role_packet": copy.deepcopy({
            key: value for key, value in role_packet.items()
            if key not in {"payload", "rendered_packet", "exact_model_input", "base_rendered_packet",
                           "mandatory_rendered_packet", "mandatory_serialized_payload"}
        }),
    }
    result = copy.deepcopy(payload)
    result.update({
        "packet": copy.deepcopy(payload),
        "role_packet": copy.deepcopy(role_packet),
        "observability": observability,
        "selected_surface_ids": selected_ids,
        "serialized_surface_ids": serialized_ids,
        "dropped_surface_ids": dropped_ids,
        "impact_seed_ids": observability["impact_seed_ids"],
        "packet_chars": packet_chars,
        "estimated_tokens": observability["estimated_tokens"],
        "packet_complete": complete,
        "status": "READY" if complete else (
            role_packet.get("status") if role_packet.get("status") != "READY"
            else IMPACT_PLANNING_CONTEXT_INCOMPLETE
        ),
        "errors": errors[:24],
        "impact_seeds": copy.deepcopy(seeds),
        "seed_validation": seed_validation,
        "selection": selection,
        "canonical_mandatory_planning_core": copy.deepcopy(mandatory_core),
        "mandatory_payload_audit": copy.deepcopy(mandatory_payload_audit),
        "mandatory_semantic_coverage": copy.deepcopy(
            mandatory_core.get("mandatory_semantic_coverage", [])
        ),
        "mandatory_core_hash": mandatory_core.get("mandatory_core_hash"),
    })
    return result


build_complete_planning_packet = build_canonical_planning_packet
build_planner_packet = build_canonical_planning_packet


def validate_planning_packet(packet, registry=None, requirements=None, impact_seeds=None,
                              max_chars=MAX_PLANNER_CONTEXT_CHARS):
    """Independently verify complete planner-packet authority and retention."""
    wrapper = packet if isinstance(packet, dict) else {}
    value = wrapper.get("packet") if isinstance(wrapper.get("packet"), dict) else wrapper
    role_packet = wrapper.get("role_packet") if isinstance(wrapper.get("role_packet"), dict) else None
    surfaces = [item for item in list(value.get("surfaces", []) or []) if isinstance(item, dict)]
    serialized_ids = [str(item.get("surface_id")) for item in surfaces]
    selected_ids = [str(item) for item in wrapper.get("selected_surface_ids", serialized_ids)]
    seeds = list(impact_seeds if impact_seeds is not None else value.get("impact_seeds", []) or [])
    if not seeds and isinstance(wrapper.get("impact_seeds"), list):
        seeds = list(wrapper.get("impact_seeds"))
    errors = []
    if not value.get("requirements"):
        errors.append("planner packet requirements are missing")
    full_core = wrapper.get("canonical_mandatory_planning_core")
    if isinstance(full_core, dict):
        core_validation = validate_canonical_mandatory_planning_core(full_core)
        if not core_validation.get("valid"):
            errors.extend(core_validation.get("errors", []))
    if isinstance(value.get("mandatory_core"), dict) or isinstance(full_core, dict):
        current_vs_desired = audit_current_vs_desired_representation(value)
        if not current_vs_desired.get("valid"):
            errors.append(current_vs_desired.get("error", "current/desired audit failed"))
    if selected_ids != serialized_ids:
        errors.append("selected surfaces were not serialized completely")
    if len({str(item) for item in serialized_ids}) != len(serialized_ids):
        errors.append("planner packet contains duplicate surface IDs")
    serialized_set = set(serialized_ids)
    for surface in surfaces:
        owner_id = surface.get("owner_surface_id")
        if owner_id and str(owner_id) not in serialized_set:
            errors.append(f"{surface.get('surface_id')}: owner surface is missing from packet")
    if serialized_ids and not seeds:
        errors.append("planner packet impact seeds are missing")
    seed_validation = validate_impact_seeds(
        seeds, registry or {"surfaces": surfaces}, selected_surface_ids=serialized_ids,
    )
    if not seed_validation.get("valid"):
        errors.extend(seed_validation.get("errors", []))
    if {
        normalize_impact_id(item.get("impact_id")) for item in seeds
    } != {
        normalize_impact_id(item.get("impact_id")) for item in value.get("impact_seeds", []) or []
    }:
        errors.append("planner packet impact seeds were not serialized completely")
    if role_packet is not None:
        exact_model_input = role_packet.get("exact_model_input") or role_packet.get("rendered_packet")
        if not isinstance(exact_model_input, str):
            exact_model_input = str(exact_model_input or "")
        role_limit = int(role_packet.get("hard_limit_chars") or max_chars)
        packet_chars = len(exact_model_input)
        if packet_chars > role_limit:
            errors.append("planner role packet rendered-size bound exceeded")
        if role_packet.get("rendered_chars") != packet_chars:
            errors.append("planner role packet rendered length was not audited exactly")
        if role_packet.get("rendered_packet") != exact_model_input:
            errors.append("planner provider input differs from the audited rendered packet")
        if role_packet.get("mandatory_drops"):
            errors.append("planner role packet dropped mandatory content")
        hash_material = {
            key: copy.deepcopy(item) for key, item in role_packet.items()
            if key not in {
                "errors", "status", "packet_hash", "payload", "rendered_packet",
                "exact_model_input", "base_rendered_packet", "mandatory_rendered_packet",
                "mandatory_serialized_payload", "base_mandatory_rendered_chars",
            }
        }
        hash_material["rendered_packet"] = exact_model_input
        hash_material["payload"] = value
        expected_hash = _role_packet_hash(hash_material)
        if role_packet.get("packet_hash") != expected_hash:
            errors.append("planner role packet hash does not match its exact render")
        if not role_packet.get("packet_complete"):
            errors.append("planner role packet is marked incomplete")
    else:
        packet_chars = len(_compact_json(value))
        if packet_chars > max(1, int(max_chars)):
            errors.append("planner packet serialized-size bound exceeded")
    if wrapper.get("packet_complete") is False or value.get("packet_complete") is False:
        errors.append("planner packet is marked incomplete")
    return {
        "valid": not errors,
        "errors": errors[:24],
        "selected_surface_ids": selected_ids,
        "serialized_surface_ids": serialized_ids,
        "impact_seed_ids": [normalize_impact_id(item.get("impact_id")) for item in seeds],
        "packet_chars": packet_chars,
        "estimated_tokens": _estimated_tokens(_compact_json(value)),
        "packet_complete": not errors,
        "current_vs_desired": audit_current_vs_desired_representation(value),
    }


def build_planner_context(task_brain, requirements, evidence, project_invariants=None,
                          surface_registry=None, impact_seeds=None):
    """Backward-compatible compact context view over the new packet builder.

    The production ImpactPlanner path uses ``build_canonical_planning_packet``
    directly.  This compatibility view retains the historic evidence key used
    by callers while keeping canonical surfaces and seeds intact.
    """
    result = build_canonical_planning_packet(
        task_brain, requirements, evidence, project_invariants=project_invariants,
        surface_registry=surface_registry,
    )
    packet = copy.deepcopy(result.get("packet", result))
    # A caller-supplied seed list is accepted for compatibility only when it
    # is already the same deterministic surface-bound set; it cannot replace
    # packet authority.
    if impact_seeds is not None:
        supplied_ids = [normalize_impact_id(item.get("impact_id")) for item in list(impact_seeds or [])]
        packet_ids = [normalize_impact_id(item.get("impact_id")) for item in packet.get("impact_seeds", [])]
        if supplied_ids == packet_ids:
            packet["impact_seeds"] = copy.deepcopy(list(impact_seeds or []))
    packet["source_requirements"] = copy.deepcopy(packet.get("requirements", []))
    # Preserve the historical compact compatibility view.  The complete role
    # audit is available as ``result['role_packet']``; copying it into this
    # legacy model context would make the compatibility projection itself
    # exceed the old serialized bound.
    observability = result.get("observability", {})
    packet["packet_observability"] = {
        key: copy.deepcopy(observability.get(key))
        for key in (
            "selected_surface_ids", "serialized_surface_ids", "dropped_surface_ids",
            "impact_seed_ids", "packet_chars", "payload_chars", "estimated_tokens",
            "packet_complete",
        )
    }
    packet["packet_complete"] = bool(result.get("packet_complete"))
    # The legacy projection is still required to fit its historical JSON
    # representation, which uses ordinary JSON separators.  Keep this
    # compatibility-only view bounded by removing complete optional records;
    # the production role compiler above uses the exact role renderer and is
    # authoritative for provider packets.
    def legacy_size(value):
        return len(json.dumps(value, ensure_ascii=False, default=str))

    while legacy_size(packet) > MAX_PLANNER_CONTEXT_CHARS:
        removed = False
        project = packet.get("project_context")
        if isinstance(project, list) and project:
            project.pop()
            removed = True
        if removed:
            continue
        task_facts = packet.get("task_facts")
        if isinstance(task_facts, dict):
            for field in (
                "known_non_goals", "acceptance_conditions", "relevant_dependencies",
                "current_interfaces", "current_state_ownership", "current_owners",
                "relevant_tests", "user_confirmed_decisions",
            ):
                values = task_facts.get(field)
                if isinstance(values, list) and values:
                    values.pop()
                    removed = True
                    break
                if isinstance(values, list) and not values:
                    task_facts.pop(field, None)
            if not removed and task_facts:
                packet["task_facts"] = {}
                removed = True
        if removed:
            continue
        evidence = packet.get("accepted_repository_evidence")
        if isinstance(evidence, list) and evidence:
            evidence.pop()
            continue
        # Audit presentation is optional in this compatibility projection.
        # It is removed only after optional semantic facts have been tried.
        if packet.pop("packet_observability", None) is not None:
            continue
        break
    return packet


def impact_map_schema():
    """Schema for the bounded planner response.

    The planner decides semantics for deterministic impact slots.  The
    ``surface_id`` is intentionally optional for existing surfaces: surface
    binding is supplied by the orchestrator's seed.  Repository identity is
    not part of the model-facing decision contract.
    """
    entry = {
        "type": "object",
        "properties": {
            "impact_id": {"type": "string"},
            "surface_id": {"type": "string"},
            "disposition": {"type": "string", "enum": list(DISPOSITIONS)},
            "action": {"type": "string"},
            "interfaces_to_reuse": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "verification": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "new_surface_proposal_ids": {
                "type": "array", "items": {"type": "string"}, "maxItems": 4,
            },
            "requirement_ids": {
                "type": "array", "items": {"type": "string"},
                "minItems": 1, "maxItems": MAX_REQUIREMENT_REFS_PER_IMPACT,
            },
            "reason": {"type": "string"},
            "preserve": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "test_contract": {
                "type": "array", "items": {"type": "string"}, "maxItems": 6,
            },
        },
        "required": [
            "impact_id", "disposition", "requirement_ids",
        ],
        "anyOf": [{"required": ["action"]}, {"required": ["reason"]}],
        "additionalProperties": False,
    }
    new_surface = {
        "type": "object",
        "properties": {
            "proposal_id": {"type": "string"},
            "kind": {"type": "string"},
            "requirement_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "reason_existing_surfaces_insufficient": {"type": "string"},
            "parent_scope": {"type": "string"},
            "intended_responsibility": {"type": "string"},
            "verification_responsibility": {"type": "string"},
        },
        "required": [
            "proposal_id", "kind", "requirement_ids", "reason_existing_surfaces_insufficient",
            "parent_scope", "intended_responsibility", "verification_responsibility",
        ],
        "additionalProperties": False,
    }
    root_properties = {
        "task_goal": {"type": "string"},
        "impacts": {
            "type": "array", "items": entry, "minItems": 1,
            "maxItems": MAX_IMPACT_ENTRIES,
        },
        "integration_verification": {
            "type": "array", "items": {"type": "string"}, "maxItems": 10,
        },
        "insufficient_evidence": {
            "type": "array", "items": {"type": "string"}, "maxItems": 6,
        },
        "new_surface_proposals": {
            "type": "array", "items": new_surface, "maxItems": 4,
        },
    }
    # Accept the single-decision shape seen in the v18.1 recovery artifact as
    # well as the normal {"impacts": [...]} envelope.  The outer properties
    # include the semantic entry fields so a provider-side JSON-schema
    # validator can accept the bounded direct form without duplicating the
    # repository-identity contract.
    for key, value in entry["properties"].items():
        root_properties.setdefault(key, value)
    return {
        "type": "object",
        "properties": root_properties,
        "anyOf": [
            {"required": ["impacts"]},
            {
                "required": ["impact_id", "disposition", "requirement_ids"],
                "anyOf": [{"required": ["action"]}, {"required": ["reason"]}],
            },
        ],
        "additionalProperties": False,
    }


def _disposition_for_impact(item):
    raw = str(item.get("disposition", "")).upper().strip()
    if raw in DISPOSITIONS:
        return raw
    # An explicitly supplied unknown disposition is invalid.  Do not silently
    # reinterpret it as MUST_CHANGE from a legacy impact kind; per-decision
    # validation needs to be able to reject just this decision.
    if "disposition" in item and raw:
        return raw
    kind = str(item.get("impact_kind", "")).upper().strip()
    necessity = str(item.get("necessity_status", "")).upper().strip()
    if necessity == "PRESERVATION_ONLY" or kind == "PRESERVATION_ONLY":
        return "PRESERVATION_ONLY"
    if kind == "TEST_CHANGE":
        return "TEST_CHANGE"
    if kind == "INTERFACE_REUSE":
        return "INTERFACE_REUSE"
    if kind == "CROSS_CUTTING_VERIFICATION":
        return "VERIFY_ONLY"
    if necessity == "MUST_CHANGE":
        return "MUST_CHANGE"
    if necessity == "INSUFFICIENT_EVIDENCE":
        return "INSUFFICIENT_EVIDENCE"
    return "MUST_CHANGE" if kind in {"BEHAVIOR_CHANGE", "INTEGRATION_CHANGE"} else "VERIFY_ONLY"


def _impact_kind_for_disposition(disposition, legacy_kind=""):
    return {
        "MUST_CHANGE": str(legacy_kind or "BEHAVIOR_CHANGE").upper()
        if str(legacy_kind or "").upper() in IMPACT_KINDS
        and str(legacy_kind or "").upper() not in {"PRESERVATION_ONLY", "INTERFACE_REUSE", "TEST_CHANGE"}
        else "BEHAVIOR_CHANGE",
        "INTERFACE_REUSE": "INTERFACE_REUSE",
        "TEST_CHANGE": "TEST_CHANGE",
        "PRESERVATION_ONLY": "PRESERVATION_ONLY",
        "VERIFY_ONLY": "CROSS_CUTTING_VERIFICATION",
        "INSUFFICIENT_EVIDENCE": "INTEGRATION_CHANGE",
    }.get(disposition, "INTEGRATION_CHANGE")


# ---------------------------------------------------------------------------
# V24.3 AUTHORITY-INHERITED IMPACT DECISION FRAME
# ---------------------------------------------------------------------------

# This audit is intentionally data, rather than a comment in the prompt.  It
# is used by tests and by the frame compiler to make a field's authority
# visible before a model is invoked.
_IMPACT_MAP_FIELD_OWNERSHIP = {
    "impact_id": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "impact seed", "required": True,
        "model_writable": False,
    },
    "seed_id": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "impact seed", "required": True,
        "model_writable": False,
    },
    "surface_id": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "canonical surface registry / seed",
        "required": True, "model_writable": False,
    },
    "decision_kind": {
        "owner": "MODEL_DECISION", "source": "bounded frame decision", "required": True,
        "model_writable": True,
    },
    "disposition": {
        "owner": "MODEL_DECISION", "source": "bounded frame decision", "required": True,
        "model_writable": True,
    },
    "preservation_promises": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "frame inheritance", "required": True,
        "model_writable": False,
    },
    "preserve": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "frame inheritance", "required": True,
        "model_writable": False,
    },
    "verification_contracts": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "frame inheritance", "required": True,
        "model_writable": False,
    },
    "verification": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "frame inheritance", "required": True,
        "model_writable": False,
    },
    "test_contract": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "frame inheritance", "required": False,
        "model_writable": False,
    },
    "mutation_target": {
        "owner": "MODEL_DECISION", "source": "chosen target constrained by frame",
        "required": False, "model_writable": True,
    },
    "reuse_target": {
        "owner": "MODEL_DECISION", "source": "chosen target constrained by frame",
        "required": False, "model_writable": True,
    },
    "interfaces_to_reuse": {
        "owner": "MODEL_DECISION", "source": "frame-authorized interface target",
        "required": False, "model_writable": True,
    },
    "rationale": {
        "owner": "MODEL_OPTIONAL", "source": "bounded_rationale", "required": False,
        "model_writable": True,
    },
    "reason": {
        "owner": "MODEL_OPTIONAL", "source": "bounded_rationale", "required": False,
        "model_writable": True,
    },
    "action": {
        "owner": "MODEL_DECISION", "source": "validated bounded rationale", "required": True,
        "model_writable": True,
    },
    "candidate_change": {
        "owner": "MODEL_DECISION", "source": "validated bounded rationale", "required": True,
        "model_writable": True,
    },
    "scope_notes": {
        "owner": "DETERMINISTIC_REPOSITORY_EVIDENCE", "source": "canonical surface / evidence",
        "required": False, "model_writable": False,
    },
    "path": {
        "owner": "DETERMINISTIC_REPOSITORY_EVIDENCE", "source": "canonical surface registry",
        "required": True, "model_writable": False,
    },
    "symbols": {
        "owner": "DETERMINISTIC_REPOSITORY_EVIDENCE", "source": "canonical surface registry",
        "required": False, "model_writable": False,
    },
    "risk_notes": {
        "owner": "MODEL_OPTIONAL", "source": "bounded model rationale", "required": False,
        "model_writable": True,
    },
    "current_owner": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "verified ownership evidence",
        "required": True, "model_writable": False,
    },
    "owner": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "verified ownership evidence",
        "required": True, "model_writable": False,
    },
    "dnt": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "VerifiedPlanningContext",
        "required": True, "model_writable": False,
    },
    "prohibitions": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "VerifiedPlanningContext",
        "required": True, "model_writable": False,
    },
    "requirement_ids": {
        "owner": "DETERMINISTIC_AUTHORITY", "source": "impact seed / Source Requirements",
        "required": True, "model_writable": False,
    },
    "repository_evidence_ids": {
        "owner": "DETERMINISTIC_REPOSITORY_EVIDENCE", "source": "canonical surface registry",
        "required": True, "model_writable": False,
    },
}


def impact_map_field_ownership():
    """Return the V24.3 required-field authority audit."""
    return copy.deepcopy(_IMPACT_MAP_FIELD_OWNERSHIP)


audit_impact_map_field_ownership = impact_map_field_ownership
field_ownership_audit = impact_map_field_ownership


def impact_decision_frame_schema():
    """Schema for the immutable authority-bound pre-model decision frame."""
    obligation = {
        "type": "object",
        "properties": {
            "obligation_id": {"type": "string"},
            "text": {"type": "string"},
            "requirement_ids": {"type": "array", "items": {"type": "string"}},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "structured_relations": {"type": "array", "items": {"type": "string"}},
            "provenance": {"type": "string"},
        },
        "required": ["obligation_id", "text", "requirement_ids", "evidence_refs"],
        "additionalProperties": False,
    }
    slot = {
        "type": "object",
        "properties": {
            "slot_id": {"type": "string"},
            "separate_decision": {"type": "boolean"},
            "seed_id": {"type": "string"},
            "impact_id": {"type": "string"},
            "surface_id": {"type": "string"},
            "surface_kind": {"type": "string"},
            "surface_role": {"type": "string"},
            "surface_path": {"type": "string"},
            "surface_symbol": {"type": "string"},
            "surface_structured_relations": {"type": "array", "items": {"type": "string"}},
            "structured_obligation_binding": {"type": "boolean"},
            "requirement_ids": {"type": "array", "items": {"type": "string"}},
            "allowed_decisions": {"type": "array", "items": {"type": "string"}},
            "candidate_obligation_ids": {"type": "array", "items": {"type": "string"}},
            "surface_capabilities": {
                "type": "array", "items": {"type": "string", "enum": list(DECISION_CAPABILITY_NAMES)},
            },
            "decision_capabilities": {
                "type": "object",
                "additionalProperties": {"type": "array", "items": {"type": "string"}},
            },
            "obligations_satisfied_by_decision": {
                "type": "object",
                "additionalProperties": {"type": "array", "items": {"type": "string"}},
            },
            "inherited_obligation_ids": {"type": "array", "items": {"type": "string"}},
            "allowed_targets": {"type": "array", "items": {"type": "string"}},
            "authority_change_targets": {"type": "array", "items": {"type": "string"}},
            "current_owner": {"type": ["object", "null"]},
            "required_interfaces": {"type": "array", "items": {"type": "string"}},
            "interface_provenance": {"type": "array", "items": {"type": "object"}},
            "required_preservation_promises": {"type": "array", "items": obligation},
            "required_verification_contracts": {"type": "array", "items": obligation},
            "dnt": {"type": "array", "items": {"type": "string"}},
            "prohibitions": {"type": "array", "items": {"type": "string"}},
            "dnt_surface_ids": {"type": "array", "items": {"type": "string"}},
            "prohibited_surface_ids": {"type": "array", "items": {"type": "string"}},
            "authority_refs": {"type": "array", "items": {"type": "string"}},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "slot_id", "seed_id", "impact_id", "surface_id", "requirement_ids",
            "surface_kind", "surface_role", "surface_path", "surface_symbol",
            "allowed_decisions", "candidate_obligation_ids", "surface_capabilities",
            "decision_capabilities", "obligations_satisfied_by_decision",
            "inherited_obligation_ids", "allowed_targets", "current_owner", "required_interfaces",
            "required_preservation_promises", "required_verification_contracts", "dnt",
            "prohibitions", "dnt_surface_ids", "prohibited_surface_ids",
            "authority_refs", "evidence_refs",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "version": {"type": "string"},
            "artifact_type": {"type": "string"},
            "project_id": {"type": ["string", "null"]},
            "task_id": {"type": ["string", "null"]},
            "authority_change_authorized": {"type": "boolean"},
            "authority_change_targets": {"type": "array", "items": {"type": "string"}},
            "source_planning_context_hash": {"type": "string"},
            "source_mandatory_core_hash": {"type": "string"},
            "requirement_obligation_ledger": {"type": "object"},
            "impact_decision_frame_coverage": {"type": "object"},
            "coverage": {"type": "object"},
            "decision_slots": {"type": "array", "items": slot},
            "frame_errors": {"type": "array", "items": {"type": "string"}},
            "frame_complete": {"type": "boolean"},
            "frame_coverage_ready": {"type": "boolean"},
            "structured_obligation_binding": {"type": "boolean"},
            "frame_hash": {"type": "string"},
        },
        "required": [
            "version", "artifact_type", "project_id", "task_id",
            "source_planning_context_hash", "source_mandatory_core_hash",
            "requirement_obligation_ledger", "impact_decision_frame_coverage", "coverage",
            "decision_slots", "frame_errors", "frame_complete", "frame_coverage_ready",
            "frame_hash",
        ],
        "additionalProperties": False,
    }


def impact_decision_choice_schema():
    """Schema for the small ImpactPlanner choice-only response."""
    choice = {
        "type": "object",
        "properties": {
            "slot_id": {"type": "string"},
            "decision": {"type": "string", "enum": list(IMPACT_DECISION_CHOICES)},
            "chosen_target": {"type": "string"},
            "reason_code": {"type": "string"},
            "bounded_rationale": {"type": "string"},
        },
        "required": list(IMPACT_DECISION_MODEL_FIELDS),
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array", "items": choice, "minItems": 1,
                "maxItems": MAX_IMPACT_SEEDS,
            },
        },
        "required": ["decisions"],
        "additionalProperties": False,
    }


def _impact_decision_hash(value):
    return hashlib.sha256(_compact_json(value).encode("utf-8")).hexdigest()


def impact_decision_frame_hash(frame):
    value = copy.deepcopy(frame if isinstance(frame, dict) else {})
    value.pop("frame_hash", None)
    return _impact_decision_hash(value)


def impact_decision_choice_hash(frame, choices):
    value = choices if isinstance(choices, dict) else {"decisions": choices or []}
    if isinstance(value, dict):
        decisions = list(value.get("decisions", value.get("choices", [])) or [])
    else:
        decisions = []
    decisions = [copy.deepcopy(item) for item in decisions if isinstance(item, dict)]
    decisions.sort(key=lambda item: str(item.get("slot_id") or ""))
    return _impact_decision_hash({
        "frame_hash": (frame or {}).get("frame_hash") if isinstance(frame, dict) else None,
        "decisions": decisions,
    })


impact_decision_choices_hash = impact_decision_choice_hash


def _frame_text(value):
    if isinstance(value, dict):
        raw = value.get("text")
        if raw in (None, ""):
            raw = value.get("fact")
        if isinstance(raw, dict):
            raw = raw.get("text") or raw.get("fact") or raw.get("summary")
        if raw in (None, ""):
            raw = value.get("summary") or value.get("description") or value.get("condition")
    else:
        raw = value
    return _compact(raw, 520)


def _frame_ids(value, keys):
    result = []
    if not isinstance(value, dict):
        return result
    for key in keys:
        raw = value.get(key)
        values = raw if isinstance(raw, (list, tuple, set)) else ([] if raw in (None, "") else [raw])
        for item in values:
            if isinstance(item, dict):
                item = (
                    item.get("id") or item.get("record_id") or item.get("evidence_id")
                    or item.get("surface_id") or item.get("slot_id")
                )
            if item not in (None, ""):
                text = str(item)
                if text not in result:
                    result.append(text)
    return result


def _frame_record_id(value, fallback=""):
    if isinstance(value, dict):
        for key in (
            "obligation_id", "record_id", "authority_record_id", "evidence_id",
            "constraint_id", "verification_id", "test_id", "acceptance_id",
        ):
            if value.get(key) not in (None, ""):
                return str(value[key])
    return str(fallback or "")


def _frame_record_refs(value):
    if not isinstance(value, dict):
        return {"requirement_ids": [], "evidence_refs": [], "authority_refs": []}
    requirement_ids = _frame_ids(value, ("requirement_ids", "source_requirement_ids"))
    evidence_refs = _frame_ids(value, ("evidence_ids", "evidence_refs", "repository_evidence_ids"))
    authority_refs = _frame_ids(value, (
        "authority_refs", "source_ids", "source_references", "current_authority_ids",
    ))
    record_id = _frame_record_id(value)
    if record_id and record_id not in authority_refs and not record_id.startswith("REPO-"):
        authority_refs.append(record_id)
    return {
        "requirement_ids": requirement_ids[:MAX_REQUIREMENT_REFS_PER_IMPACT],
        "evidence_refs": evidence_refs[:MAX_EVIDENCE_REFS_PER_IMPACT],
        "authority_refs": authority_refs[:16],
    }


def _frame_record_is_current(value):
    """Reject explicitly stale or contradicted facts at the frame boundary."""
    if not isinstance(value, dict):
        return False
    stale_markers = {
        "STALE", "STALE_VERIFIED", "STALE_WARNING", "STALE_VERIFIED_EVIDENCE",
        "CONFIRMED_DRIFT", "AUTHORITY_IMPLEMENTATION_DRIFT",
    }
    for key in ("classification", "status", "drift_classification", "kind"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip().upper() in stale_markers:
            return False
    if value.get("stale") is True or value.get("drift_confirmed") is True:
        return False
    return True


def _frame_surface_terms(surface, requirements=None, requirement_ids=None, include_requirements=False):
    texts = [
        surface.get("verified_fact", ""), surface.get("fact", ""), surface.get("path", ""),
        surface.get("symbol", ""), surface.get("role", ""), surface.get("kind", ""),
    ]
    if include_requirements:
        by_id = {item["requirement_id"]: item for item in active_requirements(requirements or [])}
        for requirement_id in list(requirement_ids or []):
            if requirement_id in by_id:
                texts.append(by_id[requirement_id].get("text", ""))
    return _domain_tokens(" ".join(str(item) for item in texts))


def _frame_record_matches(record, surface, requirement_ids, requirements, *, global_record=False):
    if not isinstance(record, dict) or not isinstance(surface, dict):
        return False
    if not _frame_record_is_current(record):
        return False
    refs = _frame_record_refs(record)
    surface_id = str(surface.get("surface_id") or "")
    explicit_surface_ids = set(_frame_ids(record, (
        "surface_id", "canonical_surface_id", "surface_ids", "target_surface_ids",
        "candidate_surface_ids", "authorized_surface_ids", "implementation_surface_ids",
        "dnt_surface_ids", "prohibited_surface_ids", "forbidden_surface_ids",
        "do_not_touch_surface_ids", "do_not_modify_surface_ids",
    )))
    if surface_id and surface_id in explicit_surface_ids:
        return True
    surface_evidence = {str(item) for item in surface.get("evidence_ids", []) or []}
    if surface_evidence.intersection(refs["evidence_refs"]):
        return True
    path = _normal_path(record.get("path"))
    symbol = str(record.get("symbol") or "").strip()
    surface_path = _normal_path(surface.get("path"))
    surface_symbol = str(surface.get("symbol") or "").strip()
    record_relations = set(_structured_relation_names(record))
    surface_relations = set(_surface_structured_relations(surface))
    preservation_relations = {
        item for item in record_relations
        if item.startswith("PRESERVE_")
    }
    if preservation_relations and surface_relations:
        # A typed preservation record is fail-closed: a matching path or
        # shared prose cannot bind it to a different semantic surface.
        if not preservation_relations.intersection(surface_relations):
            return False
        if refs["requirement_ids"] and not refs["requirement_ids"].intersection(
            {str(item) for item in list(requirement_ids or [])}
        ):
            return False
        return True
    if record_relations.intersection(surface_relations) and record.get("evidence_id"):
        return True
    if path and path == surface_path:
        if not symbol or symbol == surface_symbol or _surface_symbol_base(symbol) == _surface_symbol_base(surface_symbol):
            return True
    record_req_ids = set(refs["requirement_ids"])
    selected_req_ids = set(str(item) for item in list(requirement_ids or []))
    text = _frame_text(record)
    if not text:
        return bool(global_record and (not record_req_ids or record_req_ids.intersection(selected_req_ids)))
    kind = str(surface.get("kind") or "").upper()
    role = str(surface.get("role") or "").upper()
    lower_text = text.casefold()
    if re.search(r"\b(?:owner|ownership|sole|authoritative)\b", lower_text) and not (
        kind == "OWNER" or role in {"OWNER", "STATE_OWNER", "INPUT_OWNER", "INTERFACE"}
    ):
        return False
    if "pausecontroller" in lower_text and re.search(
        r"\b(?:owner|ownership|sole|authoritative)\b", lower_text,
    ) and kind == "OWNER" and _surface_symbol_base(surface.get("symbol")) != "PauseController":
        return False
    record_terms = _domain_tokens(text)
    # Requirement identity is checked separately below.  Including the full
    # compound task sentence here would make every slot appear related to
    # every preservation clause and would defeat slot locality.
    surface_terms = _frame_surface_terms(surface)
    overlap = record_terms.intersection(surface_terms)
    if record_req_ids.intersection(selected_req_ids) and overlap:
        return True
    # A global DNT/prohibition is authoritative for every selected slot.  It
    # is not a guessed relationship and does not make preservation prose
    # global; only the explicit constraint channel uses this branch.
    if global_record and not path and not symbol and not record_req_ids:
        return True
    return bool(overlap and (len(overlap) >= 2 or any(
        token in overlap for token in ("owner", "ownership", "pausecontroller", "escape", "movement", "togglepause")
    )))


def _frame_raw_records(task_brain, verified_planning_context, requirements, evidence):
    brain = task_brain if isinstance(task_brain, dict) else {}
    source = verified_planning_context if isinstance(verified_planning_context, dict) else {}
    preservation = []
    verification = []
    constraints = []

    def split_preservation_record(value):
        """Expose compound preservation clauses without inventing facts."""
        if not isinstance(value, dict):
            return [value]
        text = _frame_text(value)
        marker = re.search(
            r"\b(?:preserv\w*|keep\w*|retain\w*)\b", text, re.IGNORECASE,
        )
        if not marker:
            return [value]
        clauses = _source_preservation_clauses(text)
        if len(clauses) < 2:
            return [value]
        result = []
        for clause in clauses[:8]:
            child = copy.deepcopy(value)
            child["text"] = clause
            result.append(child)
        return result

    def add(target, values, channel, *, global_record=False):
        for index, item in enumerate(list(values or [])[:24], 1):
            if not isinstance(item, dict):
                item = {"text": item}
            records = split_preservation_record(item) if channel == "preservation" else [item]
            for child_index, child in enumerate(records, 1):
                value = copy.deepcopy(child)
                value["_frame_channel"] = channel
                value["_frame_global"] = bool(global_record)
                value["_frame_index"] = index * 10 + child_index
                target.append(value)

    for value in (brain, source):
        add(preservation, value.get("required_preservation_promises"), "preservation")
        add(preservation, value.get("preservation_promises"), "preservation")
        add(preservation, value.get("preservation_constraints"), "preservation")
        add(verification, value.get("required_verification_contracts"), "verification")
        add(verification, value.get("verification_contracts"), "verification")
        add(verification, value.get("verification_obligations"), "verification")
        add(verification, value.get("relevant_tests"), "verification")
        add(verification, value.get("acceptance_conditions"), "verification")
        add(constraints, value.get("dnt"), "dnt", global_record=True)
        add(constraints, value.get("prohibitions"), "prohibition", global_record=True)

    # Current verified/ repository facts may carry a structured preservation
    # identity even when they are not copied into the legacy preservation
    # field.  Project only those explicit identities into the frame; prose,
    # filenames, and stale/drift records are not promoted here.
    structured_current_fields = (
        "relevant_project_brain_projection", "current_verified_facts",
        "current_durable_authority", "current_authority", "current_owners",
        "current_state_ownership", "current_interfaces",
        "current_repository_evidence",
    )
    for value in (brain, source):
        for field in structured_current_fields:
            current_values = value.get(field, [])
            for item in list(current_values or [])[:24]:
                if not isinstance(item, dict) or not _frame_record_is_current(item):
                    continue
                if any(
                    relation.startswith("PRESERVE_")
                    for relation in _structured_relation_names(item)
                ):
                    add(preservation, [item], "preservation")

    # The requirement is itself deterministic authority.  It is included only
    # when its wording carries a preservation/prohibition obligation; no new
    # test or preservation statement is generated here.
    for index, item in enumerate(active_requirements(requirements), 1):
        if _PRESERVE_RE.search(item.get("text", "")) or _PROHIBITION_RE.search(item.get("text", "")):
            preservation.extend(split_preservation_record(copy.deepcopy(item)))
            for value in preservation[-8:]:
                value["_frame_channel"] = "preservation"
                value["_frame_index"] = index
        if _TEST_RE.search(item.get("text", "")):
            value = copy.deepcopy(item)
            value["_frame_channel"] = "verification"
            value["_frame_index"] = index
            verification.append(value)

    # Accepted CURRENT_TEST evidence is structured repository evidence, not a
    # model-generated test idea.  Keep it separate so the slot matcher can
    # attach it only where the current test fact is relevant.
    for index, item in enumerate(bounded_evidence(evidence, MAX_CANONICAL_SURFACES * 2), 1):
        if str(item.get("category") or "").upper() == "CURRENT_TEST":
            value = copy.deepcopy(item)
            value["_frame_channel"] = "verification"
            value["_frame_index"] = index
            verification.append(value)
    return preservation, verification, constraints


def _frame_owner_for_surface(surface, by_surface_id, task_brain=None):
    if not isinstance(surface, dict):
        return None
    owner_id = surface.get("owner_surface_id")
    owner = by_surface_id.get(str(owner_id)) if owner_id else None
    if owner is None and surface.get("kind") == "OWNER":
        owner = surface
    if owner is None and surface.get("kind") == "INTERFACE":
        candidates = [
            item for item in by_surface_id.values()
            if item.get("kind") == "OWNER"
            and _normal_path(item.get("path")) == _normal_path(surface.get("path"))
            and _surface_symbol_base(item.get("symbol")) == _surface_symbol_base(surface.get("symbol"))
        ]
        if len(candidates) == 1:
            owner = candidates[0]
    if owner is None:
        return None
    return {
        "surface_id": owner.get("surface_id"),
        "symbol": str(owner.get("symbol") or ""),
        "path": _normal_path(owner.get("path")),
        "evidence_refs": _bounded_ids(owner.get("evidence_ids"), MAX_SURFACE_EVIDENCE_IDS),
    }


def _frame_interfaces_for_surface(surface, surfaces, owner):
    result = []
    owner_id = str((owner or {}).get("surface_id") or "")
    for candidate in surfaces:
        if candidate.get("kind") != "INTERFACE":
            continue
        same_owner = owner_id and str(candidate.get("owner_surface_id") or "") == owner_id
        same_path_owner = (
            owner is not None
            and _normal_path(candidate.get("path")) == _normal_path(owner.get("path"))
            and _surface_symbol_base(candidate.get("symbol")) == _surface_symbol_base(owner.get("symbol"))
        )
        itself = str(candidate.get("surface_id")) == str(surface.get("surface_id"))
        if same_owner or same_path_owner or itself:
            result.append(candidate)
    result.sort(key=lambda item: str(item.get("surface_id") or ""))
    return result[:6]


def _frame_authority_change(requirements):
    targets = []
    authorized = False
    for item in list(requirements or []):
        if not isinstance(item, dict):
            continue
        changes = [item]
        nested = item.get("authority_change")
        if isinstance(nested, dict):
            changes.append(nested)
        for obligation in list(item.get("obligations", []) or []):
            if not isinstance(obligation, dict):
                continue
            changes.append(obligation)
            nested = obligation.get("authority_change")
            if isinstance(nested, dict):
                changes.append(nested)
        for change in changes:
            flag = any(change.get(key) is True for key in (
                "authority_change_authorized", "allows_authority_change", "change_authority",
                "explicit_authority_change",
            ))
            flag = flag or any(change.get(key) is True for key in (
                "authorized", "explicit", "requested",
            ))
            if change.get("from") and change.get("to") and str(change.get("type", "")).upper() in {
                "AUTHORITY_CHANGE", "OWNERSHIP_CHANGE", "STATE_OWNERSHIP_CHANGE",
            }:
                flag = True
            if not flag:
                continue
            authorized = True
            for key in ("to", "target", "target_owner", "new_owner", "object"):
                if change.get(key) not in (None, "") and str(change[key]) not in targets:
                    targets.append(str(change[key]))
    return authorized, targets[:4]


def _frame_allowed_decisions(
    surface, requirement_ids, requirements, authority_change=False,
    surface_forbidden=False,
):
    by_req = {item["requirement_id"]: item for item in active_requirements(requirements or [])}
    text = " ".join(by_req[item].get("text", "") for item in requirement_ids if item in by_req)
    kind = str(surface.get("kind") or "OTHER").upper()
    role = str(surface.get("role") or "").upper()
    change = bool(_CHANGE_RE.search(text))
    preserve = bool(_PRESERVE_RE.search(text) or _PROHIBITION_RE.search(text))
    if kind == "INTERFACE" or role == "INTERFACE":
        result = ["INTERFACE_REUSE", "INSPECT_ONLY"]
    elif kind == "TEST" or role == "CURRENT_TEST":
        result = ["TEST_CHANGE", "INSPECT_ONLY"]
    elif kind == "PERSISTENCE" or role == "PERSISTENCE_OWNER":
        result = ["PRESERVATION_ONLY", "INSPECT_ONLY"]
    elif kind == "OWNER" or role in {"OWNER", "STATE_OWNER", "INPUT_OWNER"}:
        result = ["MUST_CHANGE", "INTERFACE_REUSE", "INSPECT_ONLY"] if change else [
            "PRESERVATION_ONLY", "INTERFACE_REUSE", "INSPECT_ONLY",
        ]
    elif kind == "ENTRYPOINT" or role == "ENTRYPOINT":
        result = ["VERIFY_ONLY", "INSPECT_ONLY"]
    else:
        result = ["MUST_CHANGE", "INSPECT_ONLY"] if change and not preserve else [
            "VERIFY_ONLY", "INSPECT_ONLY",
        ]
    if authority_change and (kind == "OWNER" or role in {"OWNER", "STATE_OWNER", "INPUT_OWNER"}):
        result.append("AUTHORITY_CHANGE")
    if surface_forbidden:
        # DNT/prohibition is a mutation-scope constraint.  Keep inspect,
        # reuse, and preservation decisions available as appropriate, but do
        # not expose an implementation-capable choice for the forbidden
        # surface.
        result = [
            item for item in result
            if item in {"INTERFACE_REUSE", "INSPECT_ONLY", "PRESERVATION_ONLY", "VERIFY_ONLY"}
        ]
    return list(dict.fromkeys(item for item in result if item in IMPACT_DECISION_CHOICES))


def _frame_obligation(value, channel, ordinal, surface, requirement_ids, requirements):
    text = _frame_text(value)
    if not text:
        return None
    refs = _frame_record_refs(value)
    reqs = list(refs["requirement_ids"])
    if not reqs and _frame_record_id(value).startswith("REQ-"):
        reqs = [_frame_record_id(value)]
    reqs = _bounded_ids(list(dict.fromkeys(reqs + [str(item) for item in requirement_ids if str(item) in {
        req.get("requirement_id") for req in active_requirements(requirements or [])
    }])) if _frame_record_matches(
        value, surface, requirement_ids, requirements, global_record=bool(value.get("_frame_global")),
    ) else reqs, MAX_REQUIREMENT_REFS_PER_IMPACT)
    evidence_refs = _bounded_ids(refs["evidence_refs"], MAX_EVIDENCE_REFS_PER_IMPACT)
    record_id = _frame_record_id(value, f"{channel.upper()}-{ordinal:03d}")
    result = {
        "obligation_id": record_id,
        "text": text,
        "requirement_ids": reqs,
        "evidence_refs": evidence_refs,
        "provenance": value.get("provenance") or (
            REPOSITORY_EVIDENCE if channel == "verification" and value.get("evidence_id") else USER_STATED
        ),
    }
    relations = _structured_relation_names(value)
    if relations:
        result["structured_relations"] = relations
    return result


def _frame_deduplicate_obligations(values):
    result = []
    by_text = {}
    for item in values:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        key = str(item.get("text")).casefold()
        existing = by_text.get(key)
        if existing is not None:
            existing["requirement_ids"] = _bounded_ids(
                list(existing.get("requirement_ids", []) or [])
                + list(item.get("requirement_ids", []) or []),
                MAX_REQUIREMENT_REFS_PER_IMPACT,
            )
            existing["evidence_refs"] = _bounded_ids(
                list(existing.get("evidence_refs", []) or [])
                + list(item.get("evidence_refs", []) or []),
                MAX_EVIDENCE_REFS_PER_IMPACT,
            )
            existing["structured_relations"] = _bounded_ids(
                list(dict.fromkeys(
                    list(existing.get("structured_relations", []) or [])
                    + list(item.get("structured_relations", []) or [])
                )),
                8,
            )
            continue
        by_text[key] = item
        result.append(item)
    return result[:8]


def impact_decision_capability_taxonomy():
    """Return the deterministic capability projection of existing choices."""
    return {
        key: list(value) for key, value in DECISION_CAPABILITY_TAXONOMY.items()
    }


decision_capability_taxonomy = impact_decision_capability_taxonomy


def _decision_capabilities(decision):
    return list(DECISION_CAPABILITY_TAXONOMY.get(str(decision or "").upper(), ()))


def _surface_capabilities(surface):
    value = surface if isinstance(surface, dict) else {}
    kind = str(value.get("kind") or "OTHER").upper()
    role = str(value.get("role") or "").upper()
    if kind == "OWNER" or role in {"OWNER", "STATE_OWNER", "INPUT_OWNER"}:
        return ["IMPLEMENTATION_CHANGE", "PRESERVATION_ONLY"]
    if role == "RENDER_SURFACE":
        return ["IMPLEMENTATION_CHANGE", "PRESERVATION_ONLY"]
    if kind == "TEST" or role == "CURRENT_TEST":
        return ["TEST_CHANGE"]
    if kind == "INTERFACE" or role == "INTERFACE":
        return ["REUSE_ONLY"]
    if kind == "PERSISTENCE" or role == "PERSISTENCE_OWNER":
        return ["PRESERVATION_ONLY"]
    # Generic accepted evidence is still inspectable, but is not promoted to
    # an implementation surface without a typed OWNER/current-behavior fact.
    return []


def _obligation_surface_ids(obligation):
    value = obligation if isinstance(obligation, dict) else {}
    result = []
    for key in (
        "candidate_surface_ids", "authorized_surface_ids", "surface_ids", "surface_id",
        "candidate_surfaces", "authorized_surfaces", "target_surface_ids",
        "implementation_surface_ids", "authorized_implementation_surface_ids",
        "candidate_implementation_surface_ids",
    ):
        raw = value.get(key)
        values = raw if isinstance(raw, (list, tuple, set)) else ([] if raw in (None, "", {}) else [raw])
        for item in values:
            if isinstance(item, dict):
                item = item.get("surface_id") or item.get("id")
            if item not in (None, "") and str(item) not in result:
                result.append(str(item))
    return result[:8]


def _obligation_forbidden_surface_ids(obligation):
    value = obligation if isinstance(obligation, dict) else {}
    result = []
    for key in (
        "dnt_surface_ids", "prohibited_surface_ids", "forbidden_surface_ids",
        "do_not_touch_surface_ids", "do_not_modify_surface_ids",
    ):
        raw = value.get(key)
        values = raw if isinstance(raw, (list, tuple, set)) else (
            [] if raw in (None, "", {}) else [raw]
        )
        for item in values:
            if isinstance(item, dict):
                item = item.get("surface_id") or item.get("id")
            if item not in (None, "") and str(item) not in result:
                result.append(str(item))
    return result[:8]


def _obligation_slot_ids(obligation):
    value = obligation if isinstance(obligation, dict) else {}
    raw = value.get("candidate_slot_ids") or value.get("slot_ids")
    values = raw if isinstance(raw, (list, tuple, set)) else ([] if raw in (None, "", {}) else [raw])
    return [str(item) for item in values if item not in (None, "")][:8]


def _frame_surface_is_forbidden(surface, slot):
    """Check only explicit DNT/prohibition targeting, not generic preservation."""
    value = surface if isinstance(surface, dict) else {}
    slot = slot if isinstance(slot, dict) else {}
    surface_id = str(value.get("surface_id") or "")
    path = _normal_path(value.get("path"))
    symbol = str(value.get("symbol") or "")
    explicit_dnt = {
        str(item) for item in list(slot.get("dnt_surface_ids", []) or [])
    }
    explicit_prohibited = {
        str(item) for item in list(slot.get("prohibited_surface_ids", []) or [])
    }
    if surface_id and (surface_id in explicit_dnt or surface_id in explicit_prohibited):
        return True
    for text in list(slot.get("dnt", []) or []) + list(slot.get("prohibitions", []) or []):
        text = str(text or "")
        lower = text.casefold()
        # "Do not create a second owner" constrains ownership migration but
        # does not prohibit changing the verified owner surface itself.
        targeted = re.search(
            r"\b(?:do not|don't|must not|never)\s+(?:touch|modify|change|mutate|use)\b|"
            r"\b(?:prohibited|forbidden)\b",
            lower,
        )
        if not targeted:
            continue
        normalized_text = lower.replace("\\", "/")
        normalized_path = path.casefold().replace("\\", "/")
        # Match an explicitly named canonical path/symbol/slot.  Do not use
        # broad token overlap here: a shared token such as ``src`` or
        # ``pause`` would incorrectly prohibit every neighboring surface.
        if normalized_path and re.search(
            rf"(?<![a-z0-9_]){re.escape(normalized_path)}(?![a-z0-9_])",
            normalized_text,
        ):
            return True
        if surface_id and surface_id.casefold() in normalized_text:
            return True
        symbol_base = _surface_symbol_base(symbol).casefold()
        if symbol_base and re.search(
            rf"(?<![a-z0-9_]){re.escape(symbol_base)}(?![a-z0-9_])",
            normalized_text,
        ):
            return True
        # Do not infer a target from shared prose tokens.  A path, surface
        # ID, or symbol is required for a mutation prohibition to bind to a
        # canonical surface; otherwise this constraint remains a general
        # preservation/authority rule rather than a surface prohibition.
    return False


def _frame_obligation_relevant(obligation, slot, surface):
    value = obligation if isinstance(obligation, dict) else {}
    slot = slot if isinstance(slot, dict) else {}
    surface = surface if isinstance(surface, dict) else {}
    requirement_id = str(value.get("requirement_id") or "")
    if requirement_id not in {str(item) for item in slot.get("requirement_ids", []) or []}:
        return False
    obligation_type = str(value.get("obligation_type") or "").upper()
    surface_ids = _obligation_surface_ids(value)
    if surface_ids and str(surface.get("surface_id")) not in set(surface_ids):
        return False
    if (
        obligation_type != "PROHIBITION"
        and str(surface.get("surface_id")) in set(_obligation_forbidden_surface_ids(value))
    ):
        return False
    slot_ids = _obligation_slot_ids(value)
    if slot_ids and str(slot.get("slot_id")) not in set(slot_ids):
        return False
    if value.get("requires_explicit_surface_binding") and not surface_ids and not slot_ids:
        return False
    if obligation_type != "PROHIBITION" and _frame_surface_is_forbidden(surface, slot):
        return False
    required_relations = set(_obligation_structured_relations(value))
    if slot.get("structured_obligation_binding") and required_relations:
        surface_relations = set(_surface_structured_relations(surface))
        if not required_relations.intersection(surface_relations):
            return False
    kind = str(surface.get("kind") or "OTHER").upper()
    role = str(surface.get("role") or "").upper()
    if obligation_type == "BEHAVIOR_CHANGE":
        return "IMPLEMENTATION_CHANGE" in _surface_capabilities(surface)
    if obligation_type == "TEST":
        return kind == "TEST" or role == "CURRENT_TEST"
    if obligation_type == "ARCHITECTURE_REUSE":
        return kind == "INTERFACE" or role == "INTERFACE"
    if obligation_type == "PRESERVATION":
        return True
    if obligation_type == "PROHIBITION":
        return True
    if obligation_type == "AUTHORITY_CHANGE":
        return kind == "OWNER" or role in {"OWNER", "STATE_OWNER", "INPUT_OWNER"}
    if obligation_type == "CROSS_CUTTING":
        return True
    return False


def _frame_inherited_obligation(obligation, slot):
    value = obligation if isinstance(obligation, dict) else {}
    slot = slot if isinstance(slot, dict) else {}
    obligation_type = str(value.get("obligation_type") or "").upper()
    requirement_id = str(value.get("requirement_id") or "")
    if requirement_id not in {str(item) for item in slot.get("requirement_ids", []) or []}:
        return False
    surface_id = str(slot.get("surface_id") or "")
    bound_surfaces = _obligation_surface_ids(value)
    if bound_surfaces and surface_id not in set(bound_surfaces):
        return False
    bound_slots = _obligation_slot_ids(value)
    if bound_slots and str(slot.get("slot_id") or "") not in set(bound_slots):
        return False
    if (
        obligation_type != "PROHIBITION"
        and surface_id in set(_obligation_forbidden_surface_ids(value))
    ):
        return False
    required_relations = set(_obligation_structured_relations(value))
    if slot.get("structured_obligation_binding") and required_relations:
        matched_current_record = False
        for item in list(slot.get("required_preservation_promises", []) or []):
            if not isinstance(item, dict) or not _frame_record_is_current(item):
                continue
            item_requirement_ids = {
                str(ref) for ref in item.get("requirement_ids", []) or []
            }
            if item_requirement_ids and requirement_id not in item_requirement_ids:
                continue
            if required_relations.intersection(_structured_relation_names(item)):
                matched_current_record = True
                break
        if not matched_current_record:
            return False
        # A named current-state relation is the complete inheritance proof in
        # V24.4.2 structured mode.  Do not require the source observation to
        # repeat the exact natural-language wording of the obligation.
        return True
    if value.get("inherited") is True or value.get("inherited_satisfaction") is True:
        return True
    if obligation_type == "PROHIBITION":
        return bool(slot.get("dnt") or slot.get("prohibitions"))
    if obligation_type != "PRESERVATION":
        return False
    meaning_terms = _domain_tokens(re.sub(
        r"^\s*(?:preserv\w*|keep\w*|retain\w*)\s+", "",
        str(value.get("meaning") or value.get("text") or ""),
        flags=re.IGNORECASE,
    ))
    for item in list(slot.get("required_preservation_promises", []) or []):
        if not isinstance(item, dict):
            continue
        item_requirement_ids = {str(ref) for ref in item.get("requirement_ids", []) or []}
        if item_requirement_ids and requirement_id not in item_requirement_ids:
            continue
        item_terms = _domain_tokens(re.sub(
            r"^\s*(?:preserv\w*|keep\w*|retain\w*)\s+", "",
            str(item.get("text") or ""),
            flags=re.IGNORECASE,
        ))
        if meaning_terms.intersection(item_terms):
            return True
    return False


def _frame_decision_satisfies_obligation(obligation, slot, decision, surface):
    if not _frame_obligation_relevant(obligation, slot, surface):
        return False
    decision = str(decision or "").upper()
    capabilities = set(_decision_capabilities(decision))
    obligation_type = str(obligation.get("obligation_type") or "").upper()
    kind = str(surface.get("kind") or "OTHER").upper()
    role = str(surface.get("role") or "").upper()
    if obligation_type == "BEHAVIOR_CHANGE":
        return "IMPLEMENTATION_CHANGE" in capabilities and (
            kind == "OWNER" or role in {"OWNER", "STATE_OWNER", "INPUT_OWNER", "RENDER_SURFACE"}
        )
    if obligation_type == "TEST":
        return "TEST_CHANGE" in capabilities and (kind == "TEST" or role == "CURRENT_TEST")
    if obligation_type == "ARCHITECTURE_REUSE":
        return "REUSE_ONLY" in capabilities and (kind == "INTERFACE" or role == "INTERFACE")
    if obligation_type == "PRESERVATION":
        return "PRESERVATION_ONLY" in capabilities
    if obligation_type == "AUTHORITY_CHANGE":
        return "AUTHORITY_CHANGE" in capabilities
    if obligation_type == "CROSS_CUTTING":
        return bool(capabilities.intersection({"TEST_CHANGE", "INSPECTION_ONLY"}))
    # Prohibitions are inherited constraints; no selected decision is allowed
    # to claim a prohibition as its implementation.
    return False


def _coverage_hash(value):
    material = copy.deepcopy(value if isinstance(value, dict) else {})
    material.pop("coverage_hash", None)
    return _impact_decision_hash(material)


def impact_decision_coverage_hash(coverage):
    return _coverage_hash(coverage)


def _build_frame_coverage(frame):
    value = frame if isinstance(frame, dict) else {}
    ledger = value.get("requirement_obligation_ledger")
    obligations = _atomic_obligation_records(ledger or [])
    slots = [
        item for item in list(value.get("decision_slots", []) or [])
        if isinstance(item, dict)
    ]
    obligation_records = []
    for obligation in obligations:
        obligation_id = str(obligation.get("obligation_id") or "")
        requirement_id = str(obligation.get("requirement_id") or "")
        candidate_slots = []
        candidate_decisions = []
        inherited_slots = []
        satisfied_by_decision = {}
        for slot in slots:
            slot_id = str(slot.get("slot_id") or "")
            if not slot_id:
                continue
            surface = {
                "surface_id": slot.get("surface_id"),
                "kind": slot.get("surface_kind"),
                "role": slot.get("surface_role"),
                "path": slot.get("surface_path"),
                "symbol": slot.get("surface_symbol"),
                "structured_relations": list(
                    slot.get("surface_structured_relations", []) or []
                ),
            }
            # Frame construction stores the surface capability projection on
            # each slot; the fallback makes the artifact useful with a small
            # hand-built frame in architecture tests.
            if _frame_obligation_relevant(obligation, slot, surface):
                candidate_slots.append(slot_id)
            if _frame_inherited_obligation(obligation, slot):
                inherited_slots.append(slot_id)
            # Derive every decision contribution from typed obligation,
            # surface capability, and the existing allowed-decision enum.  A
            # copied/tampered mapping in the frame is never treated as a
            # semantic shortcut.
            for decision in list(slot.get("allowed_decisions", []) or []):
                if _frame_decision_satisfies_obligation(obligation, slot, decision, surface):
                    decision = str(decision)
                    satisfied_by_decision.setdefault(decision, []).append(slot_id)
                    if decision not in candidate_decisions:
                        candidate_decisions.append(decision)
        candidate_slots = list(dict.fromkeys(candidate_slots + [
            slot_id for ids in satisfied_by_decision.values() for slot_id in ids
        ]))
        candidate_decisions = list(dict.fromkeys(candidate_decisions))
        obligation_type = str(obligation.get("obligation_type") or "").upper()
        inherited = bool(inherited_slots)
        if obligation_type == "PROHIBITION":
            ready = inherited
        elif obligation_type == "PRESERVATION":
            ready = inherited or "PRESERVATION_ONLY" in set(candidate_decisions)
        elif obligation_type == "BEHAVIOR_CHANGE":
            ready = any(
                "IMPLEMENTATION_CHANGE" in _decision_capabilities(decision)
                for decision in candidate_decisions
            )
        else:
            ready = bool(candidate_decisions) or inherited
        coverage_reasons = []
        if inherited:
            coverage_reasons.append("INHERITED_CURRENT")
        if any(
            "IMPLEMENTATION_CHANGE" in _decision_capabilities(decision)
            for decision in candidate_decisions
        ):
            coverage_reasons.append("CANDIDATE_IMPLEMENTATION")
        if any(
            "TEST_CHANGE" in _decision_capabilities(decision)
            for decision in candidate_decisions
        ):
            coverage_reasons.append("TEST_SUPPORTED")
        if not ready:
            coverage_reasons.append("UNCOVERED")
        evidence_refs = []
        for slot in slots:
            if str(slot.get("slot_id") or "") in set(candidate_slots + inherited_slots):
                evidence_refs.extend(slot.get("evidence_refs", []) or [])
        evidence_refs = _bounded_ids(
            list(obligation.get("evidence_refs", []) or []) + evidence_refs,
            MAX_EVIDENCE_REFS_PER_IMPACT,
        )
        obligation_records.append({
            "obligation_id": obligation_id,
            "requirement_id": requirement_id,
            "obligation_type": obligation_type,
            "meaning": _compact(obligation.get("meaning") or obligation.get("text"), 520),
            "structured_relations": _structured_relation_names(obligation),
            "candidate_slots": list(dict.fromkeys(candidate_slots)),
            "candidate_decisions": candidate_decisions,
            "inherited_satisfaction": inherited,
            "inherited_slots": list(dict.fromkeys(inherited_slots)),
            "coverage_ready": bool(ready),
            "satisfied_by_decision": {
                key: list(dict.fromkeys(value))
                for key, value in sorted(satisfied_by_decision.items())
            },
            "coverage_reasons": coverage_reasons,
            "evidence_refs": evidence_refs,
        })
    grouped = []
    by_requirement = {}
    for item in obligation_records:
        by_requirement.setdefault(item["requirement_id"], []).append(item)
    for requirement_id in sorted(by_requirement):
        grouped.append({
            "requirement_id": requirement_id,
            "obligations": by_requirement[requirement_id],
        })
    uncovered = [
        item["obligation_id"] for item in obligation_records
        if not item.get("coverage_ready")
    ]
    artifact = {
        "version": 1,
        "artifact_type": "ImpactDecisionFrameCoverage",
        "requirements": grouped,
        "obligations": obligation_records,
        "uncovered_obligations": uncovered,
        "uncovered_requirement_ids": list(dict.fromkeys(
            item["requirement_id"] for item in obligation_records
            if not item.get("coverage_ready")
        )),
        "coverage_status": (
            IMPACT_FRAME_COVERAGE_READY if not uncovered
            else IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP
        ),
        "metrics": {
            "impact_obligations_total": len(obligation_records),
            "impact_behavior_change_obligations": sum(
                item.get("obligation_type") == "BEHAVIOR_CHANGE"
                for item in obligation_records
            ),
            "impact_frame_covered_obligations": sum(
                bool(item.get("coverage_ready")) for item in obligation_records
            ),
            "impact_frame_uncovered_obligations": len(uncovered),
        },
    }
    artifact["coverage_hash"] = _coverage_hash(artifact)
    return artifact


def build_impact_decision_frame_coverage(frame):
    """Build the immutable zero-model pre-choice coverage artifact."""
    return _build_frame_coverage(frame)


def validate_impact_decision_frame_coverage(frame):
    value = frame if isinstance(frame, dict) else {}
    artifact = value.get("impact_decision_frame_coverage") or value.get("coverage")
    errors = []
    expected = _build_frame_coverage(value)
    if not isinstance(artifact, dict):
        errors.append("ImpactDecisionFrame coverage artifact is missing")
    else:
        if artifact.get("coverage_hash") != _coverage_hash(artifact):
            errors.append("ImpactDecisionFrame coverage hash does not match canonical contents")
        if artifact.get("coverage_hash") != expected.get("coverage_hash"):
            errors.append("ImpactDecisionFrame coverage does not match canonical frame contents")
        if artifact.get("uncovered_obligations") != expected.get("uncovered_obligations"):
            errors.append("ImpactDecisionFrame uncovered obligation projection is stale")
    if expected.get("coverage_status") != IMPACT_FRAME_COVERAGE_READY:
        errors.append(
            f"{IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP}: "
            + ", ".join(expected.get("uncovered_obligations", []))
        )
    return {
        "valid": not errors,
        "status": expected.get("coverage_status"),
        "errors": list(dict.fromkeys(errors))[:24],
        "coverage": copy.deepcopy(artifact if isinstance(artifact, dict) else expected),
        "uncovered_obligations": list(expected.get("uncovered_obligations", [])),
        "covered_obligations": sum(
            item.get("coverage_ready") is True
            for item in expected.get("obligations", [])
        ),
        "obligations_total": len(expected.get("obligations", [])),
        "model_calls": 0,
        "coverage_hash": expected.get("coverage_hash"),
    }


def build_impact_decision_frame(
    task_brain=None, requirements=None, evidence=None, surface_registry=None,
    impact_seeds=None, verified_planning_context=None, mandatory_core=None,
    *, registry=None, seeds=None, core=None, planning_context=None,
    obligation_ledger=None,
):
    """Build the immutable V24.4 authority-bound decision frame.

    The builder consumes only existing Stage 1/2/V24 authority.  It never
    calls a provider and it never fills a missing obligation with a guessed
    sentence.  An incomplete artifact is returned with a deterministic error
    so callers can fail before the ImpactPlanner invocation.
    """
    if surface_registry is None:
        surface_registry = registry
    if impact_seeds is None:
        impact_seeds = seeds
    if mandatory_core is None:
        mandatory_core = core
    if verified_planning_context is None:
        verified_planning_context = planning_context
    brain = task_brain if isinstance(task_brain, dict) else {}
    source = verified_planning_context if isinstance(verified_planning_context, dict) else {}
    raw_requirements = [item for item in list(requirements or []) if isinstance(item, dict)]
    reqs = active_requirements(raw_requirements)
    obligation_ledger_value = (
        copy.deepcopy(obligation_ledger)
        if isinstance(obligation_ledger, dict)
        else build_requirement_obligation_ledger(raw_requirements)
    )
    atomic_obligations = [
        item for item in _atomic_obligation_records(obligation_ledger_value)
        if str(item.get("requirement_id")) in {
            str(value.get("requirement_id")) for value in reqs
        }
    ]
    registry_value = surface_registry if isinstance(surface_registry, dict) else build_canonical_surface_registry(
        brain, evidence,
    )
    surfaces = [
        copy.deepcopy(item) for item in list(registry_value.get("surfaces", []) or [])
        if isinstance(item, dict) and item.get("surface_id")
    ]
    by_surface_id = canonical_surface_by_id(registry_value)
    if impact_seeds is None:
        impact_seeds = build_impact_seeds(brain, reqs, evidence, registry=registry_value)
    raw_seeds = [copy.deepcopy(item) for item in list(impact_seeds or []) if isinstance(item, dict)]
    raw_seeds.sort(key=lambda item: (
        str(item.get("surface_id") or ""),
        str(item.get("impact_id") or ""),
        str(item.get("seed_id") or ""),
    ))
    # Duplicate canonical surfaces are not separate decisions by default.
    # Only an explicit separate-decision marker permits two slots for one
    # surface; this keeps a provenance collision from becoming a planner
    # cardinality collision.
    deduped_seeds = []
    seen_surfaces = {}
    for seed in raw_seeds[:MAX_IMPACT_SEEDS]:
        surface_id = str(seed.get("surface_id") or "")
        separate = bool(
            seed.get("separate_decision") or seed.get("requires_separate_decision")
            or seed.get("decision_scope")
        )
        if surface_id in seen_surfaces and not separate:
            existing = seen_surfaces[surface_id]
            existing["requirement_ids"] = _bounded_ids(
                list(existing.get("requirement_ids", []) or []) + list(seed.get("requirement_ids", []) or []),
                MAX_REQUIREMENT_REFS_PER_IMPACT,
            )
            existing["evidence_ids"] = _bounded_ids(
                list(existing.get("evidence_ids", []) or []) + list(seed.get("evidence_ids", []) or []),
                MAX_SURFACE_EVIDENCE_IDS,
            )
            continue
        seen_surfaces[surface_id] = seed
        deduped_seeds.append(seed)
    raw_seeds = deduped_seeds

    source_metadata = _planner_source_metadata(brain, verified_planning_context=source)
    project_id = source.get("project_id") or brain.get("project_id")
    task_id = source.get("task_id") or brain.get("task_id")
    if mandatory_core is None:
        core_payload = {
            "project_id": project_id, "task_id": task_id,
            "task_goal": copy.deepcopy(brain.get("task_goal", "")),
            "requirements": copy.deepcopy(reqs), "surfaces": copy.deepcopy(surfaces),
            "impact_seeds": copy.deepcopy(raw_seeds),
            "preservation_constraints": copy.deepcopy(brain.get("preservation_constraints", [])),
            "prohibitions": copy.deepcopy(source.get("prohibitions", brain.get("prohibitions", []))),
            "dnt": copy.deepcopy(source.get("dnt", brain.get("dnt", []))),
        }
        mandatory_core = build_canonical_mandatory_planning_core(
            core_payload, project_id=project_id, task_id=task_id,
            source_planning_context_hash=source_metadata.get("source_planning_context_hash"),
            source_task_brain_hash=source_metadata.get("source_task_brain_hash"),
            source_reentry_hash=source_metadata.get("source_reentry_hash"),
        )
    core_value = mandatory_core if isinstance(mandatory_core, dict) else {}
    core_hash = core_value.get("mandatory_core_hash") or core_value.get("canonical_mandatory_core_hash")
    context_hash = (
        source_metadata.get("source_planning_context_hash")
        or core_value.get("source_planning_context_hash")
    )
    if not context_hash:
        context_hash = _impact_decision_hash({
            "project_id": project_id, "task_id": task_id, "requirements": reqs,
            "surface_ids": [item.get("surface_id") for item in surfaces],
            "evidence_ids": [item.get("evidence_id") for item in bounded_evidence(evidence, 64)],
        })
    if not core_hash:
        core_hash = _impact_decision_hash(core_value or {"task_id": task_id, "requirements": reqs})

    preservation_records, verification_records, constraint_records = _frame_raw_records(
        brain, source, reqs, evidence,
    )
    # The strict V24.4 binding mode is enabled only by a named relation on a
    # repository/surface observation that can actually bind a requirement to
    # a current code surface.  A planning-context projection may add exact
    # legacy Brain fact identities (for example, the current owner); those
    # identities preserve the older fixture path but do not, by themselves,
    # establish a V24.4 requirement-to-surface mapping.
    structured_sources = [
        item for item in list(evidence or []) if isinstance(item, dict)
    ]
    structured_sources.extend(
        item for item in list((registry_value or {}).get("surfaces", []) or [])
        if isinstance(item, dict)
    )
    for container in (brain, source):
        for field in ("current_repository_evidence", "repository_evidence", "evidence"):
            structured_sources.extend(
                item for item in list(container.get(field, []) or [])
                if isinstance(item, dict)
            )
    structured_obligation_binding = any(
        isinstance(item.get("structured_relations"), (list, tuple, set))
        and _structured_relation_names(item)
        for item in structured_sources
    )
    # ``active_requirements`` intentionally returns a compact compatibility
    # projection, so inspect the original records for an explicit authority
    # transition authorization before that metadata is stripped.
    authority_change, authority_targets = _frame_authority_change(raw_requirements)
    slots = []
    frame_errors = []
    req_id_set = {item["requirement_id"] for item in reqs}
    for index, seed in enumerate(raw_seeds, 1):
        surface_id = str(seed.get("surface_id") or "")
        surface = by_surface_id.get(surface_id)
        if not surface:
            frame_errors.append(f"seed {seed.get('seed_id') or index}: unknown canonical surface")
            continue
        seed_req_ids = [
            str(item) for item in list(seed.get("requirement_ids", []) or [])
            if str(item) in req_id_set
        ]
        slot_id = f"SLOT-{len(slots) + 1:03d}"
        # Structured obligation bindings are authoritative even when a seed
        # carries no lexical requirement reference.  This is the explicit
        # requirement-to-surface path; prose matching remains a fallback only.
        for obligation in atomic_obligations:
            requirement_id = str(obligation.get("requirement_id") or "")
            if not requirement_id:
                continue
            bound_surfaces = set(_obligation_surface_ids(obligation))
            bound_slots = set(_obligation_slot_ids(obligation))
            if surface_id in bound_surfaces or slot_id in bound_slots:
                seed_req_ids.append(requirement_id)
        owner = _frame_owner_for_surface(surface, by_surface_id, brain)
        interfaces = _frame_interfaces_for_surface(surface, surfaces, owner)
        slot_req_ids = list(dict.fromkeys(seed_req_ids))
        # Explicit Stage 3 brain bindings can add a requirement without
        # inventing one from surface prose.  The seed's lexical relation is
        # still the normal path; this branch only consumes structured refs.
        for field in (
            "current_owners", "current_state_ownership", "current_interfaces",
            "relevant_tests", "preservation_constraints", "acceptance_conditions",
        ):
            for item in list(brain.get(field, []) or []):
                if not isinstance(item, dict):
                    continue
                refs = _frame_record_refs(item)
                if _frame_record_matches(item, surface, slot_req_ids, reqs):
                    slot_req_ids.extend(item_id for item_id in refs["requirement_ids"] if item_id in req_id_set)
        slot_req_ids = _bounded_ids(slot_req_ids, MAX_REQUIREMENT_REFS_PER_IMPACT)
        separate = bool(
            seed.get("separate_decision") or seed.get("requires_separate_decision")
            or seed.get("decision_scope")
        )
        allowed_targets = [surface_id]
        allowed_targets.extend(str(item.get("surface_id")) for item in interfaces if item.get("surface_id"))
        allowed_targets.extend(authority_targets if authority_change and surface.get("kind") == "OWNER" else [])
        allowed_targets = list(dict.fromkeys(item for item in allowed_targets if item))[:8]
        slot_preservation = _frame_deduplicate_obligations([
            obligation for ordinal, record in enumerate(preservation_records, 1)
            if _frame_record_matches(
                record, surface, slot_req_ids, reqs,
                global_record=bool(record.get("_frame_global")),
            )
            for obligation in [_frame_obligation(record, "preservation", ordinal, surface, slot_req_ids, reqs)]
            if obligation
        ])
        slot_verification = _frame_deduplicate_obligations([
            obligation for ordinal, record in enumerate(verification_records, 1)
            if _frame_record_matches(
                record, surface, slot_req_ids, reqs,
                global_record=bool(record.get("_frame_global")),
            )
            for obligation in [_frame_obligation(record, "verification", ordinal, surface, slot_req_ids, reqs)]
            if obligation
        ])
        dnt_texts = []
        prohibition_texts = []
        constraint_refs = []
        dnt_surface_ids = []
        prohibited_surface_ids = []
        for ordinal, record in enumerate(constraint_records, 1):
            if not _frame_record_matches(
                record, surface, slot_req_ids, reqs,
                global_record=True,
            ):
                continue
            text = _frame_text(record)
            if not text:
                continue
            if text not in dnt_texts:
                dnt_texts.append(text)
            record_surface_ids = _frame_ids(
                record, (
                    "surface_id", "canonical_surface_id", "surface_ids", "target_surface_ids",
                    "candidate_surface_ids", "authorized_surface_ids", "implementation_surface_ids",
                    "dnt_surface_ids", "prohibited_surface_ids", "forbidden_surface_ids",
                    "do_not_touch_surface_ids", "do_not_modify_surface_ids",
                ),
            )
            if str(record.get("_frame_channel")) == "prohibition":
                if text not in prohibition_texts:
                    prohibition_texts.append(text)
                prohibited_surface_ids.extend(record_surface_ids)
            else:
                dnt_surface_ids.extend(record_surface_ids)
            constraint_refs.extend(_frame_record_refs(record).get("authority_refs", []))
        # An explicitly typed DNT preservation record is also a prohibition,
        # while ordinary preservation remains slot-local and is not copied to
        # unrelated surfaces.
        for obligation in slot_preservation:
            source_record = next(
                (record for record in preservation_records if _frame_record_id(record) == obligation.get("obligation_id")),
                {},
            )
            if source_record.get("constraint_type") == "DNT" or _PROHIBITION_RE.search(obligation.get("text", "")):
                if obligation.get("text") not in prohibition_texts:
                    prohibition_texts.append(obligation.get("text"))
                if obligation.get("text") not in dnt_texts:
                    dnt_texts.append(obligation.get("text"))
        authority_refs = [
            str(seed.get("seed_id") or ""), str(seed.get("impact_id") or ""), surface_id,
            *slot_req_ids, *list(surface.get("evidence_ids", []) or []),
        ]
        for item in slot_preservation + slot_verification:
            authority_refs.extend(_frame_record_refs(item).get("authority_refs", []))
            authority_refs.extend(item.get("requirement_ids", []) or [])
            authority_refs.extend(item.get("evidence_refs", []) or [])
        authority_refs.extend(constraint_refs)
        dnt_surface_ids = list(dict.fromkeys(str(item) for item in dnt_surface_ids if item))[:8]
        prohibited_surface_ids = list(dict.fromkeys(
            str(item) for item in prohibited_surface_ids if item
        ))[:8]
        provisional_constraint_slot = {
            "surface_id": surface_id,
            "dnt": _bounded_strings(dnt_texts, 8, 320),
            "prohibitions": _bounded_strings(prohibition_texts, 8, 320),
            "dnt_surface_ids": dnt_surface_ids,
            "prohibited_surface_ids": prohibited_surface_ids,
        }
        allowed_decisions = _frame_allowed_decisions(
            surface, slot_req_ids, reqs, authority_change=authority_change,
            surface_forbidden=_frame_surface_is_forbidden(
                surface, provisional_constraint_slot,
            ),
        )
        surface_capabilities = _surface_capabilities(surface)
        decision_capabilities = {
            str(decision): _decision_capabilities(decision)
            for decision in allowed_decisions
        }
        provisional_slot = {
            "slot_id": slot_id,
            "surface_id": surface_id,
            "requirement_ids": slot_req_ids,
            "dnt": _bounded_strings(dnt_texts, 8, 320),
            "prohibitions": _bounded_strings(prohibition_texts, 8, 320),
            "dnt_surface_ids": dnt_surface_ids,
            "prohibited_surface_ids": prohibited_surface_ids,
            "allowed_decisions": allowed_decisions,
            "surface_kind": surface.get("kind"),
            "surface_role": surface.get("role"),
            "surface_path": _normal_path(surface.get("path")),
            "surface_symbol": str(surface.get("symbol") or ""),
            "surface_structured_relations": list(
                _surface_structured_relations(surface)
            ),
            "structured_obligation_binding": structured_obligation_binding,
            "required_preservation_promises": slot_preservation,
            "required_verification_contracts": slot_verification,
        }
        candidate_obligation_ids = []
        inherited_obligation_ids = []
        obligations_satisfied_by_decision = {
            str(decision): [] for decision in allowed_decisions
        }
        for obligation in atomic_obligations:
            obligation_id = str(obligation.get("obligation_id") or "")
            if obligation_id and _frame_inherited_obligation(
                obligation, provisional_slot,
            ):
                inherited_obligation_ids.append(obligation_id)
            if not obligation_id or not _frame_obligation_relevant(
                obligation, provisional_slot, surface,
            ):
                continue
            candidate_obligation_ids.append(obligation_id)
            for decision in allowed_decisions:
                if _frame_decision_satisfies_obligation(
                    obligation, provisional_slot, decision, surface,
                ):
                    obligations_satisfied_by_decision[str(decision)].append(obligation_id)
        candidate_obligation_ids = list(dict.fromkeys(candidate_obligation_ids))
        inherited_obligation_ids = list(dict.fromkeys(inherited_obligation_ids))
        obligations_satisfied_by_decision = {
            key: list(dict.fromkeys(value))
            for key, value in obligations_satisfied_by_decision.items()
        }
        authority_refs.extend(candidate_obligation_ids)
        authority_refs.extend(inherited_obligation_ids)
        authority_refs = _bounded_ids([item for item in authority_refs if item], 32)
        # Retain canonical-core refs when they are explicitly tied to this
        # slot.  This does not deduplicate distinct semantic IDs by prose.
        for unit in list(core_value.get("semantic_units", []) or []):
            if not isinstance(unit, dict):
                continue
            unit_reqs = set(str(item) for item in unit.get("requirement_ids", []) or [])
            unit_evidence = set(str(item) for item in unit.get("evidence_ids", []) or [])
            if unit_reqs.intersection(slot_req_ids) or unit_evidence.intersection(surface.get("evidence_ids", [])):
                authority_refs.append(str(unit.get("semantic_id") or ""))
                authority_refs.extend(str(item) for item in unit.get("aliases", []) or [])
        authority_refs = _bounded_ids([item for item in authority_refs if item], 32)
        evidence_refs = _bounded_ids(
            list(surface.get("evidence_ids", []) or [])
            + [ref for item in slot_preservation + slot_verification for ref in item.get("evidence_refs", [])]
            + [ref for ref in constraint_refs if ref.startswith("REPO-")],
            MAX_EVIDENCE_REFS_PER_IMPACT,
        )
        interface_provenance = [{
            "surface_id": item.get("surface_id"), "symbol": item.get("symbol"),
            "path": _normal_path(item.get("path")),
            "evidence_refs": _bounded_ids(item.get("evidence_ids"), MAX_SURFACE_EVIDENCE_IDS),
        } for item in interfaces]
        slot = {
            "slot_id": slot_id,
            "seed_id": str(seed.get("seed_id") or f"SEED-{index:03d}"),
            "impact_id": normalize_impact_id(seed.get("impact_id") or f"IMPACT-{index:03d}"),
            "surface_id": surface_id,
            "requirement_ids": slot_req_ids,
            "allowed_decisions": allowed_decisions,
            "surface_kind": surface.get("kind"),
            "surface_role": surface.get("role"),
            "surface_path": _normal_path(surface.get("path")),
            "surface_symbol": str(surface.get("symbol") or ""),
            "surface_structured_relations": list(
                _surface_structured_relations(surface)
            ),
            "structured_obligation_binding": structured_obligation_binding,
            "candidate_obligation_ids": candidate_obligation_ids,
            "surface_capabilities": surface_capabilities,
            "decision_capabilities": decision_capabilities,
            "obligations_satisfied_by_decision": obligations_satisfied_by_decision,
            "inherited_obligation_ids": inherited_obligation_ids,
            "allowed_targets": allowed_targets,
            "authority_change_targets": authority_targets if authority_change else [],
            "current_owner": owner,
            "required_interfaces": [str(item.get("surface_id")) for item in interfaces],
            "interface_provenance": interface_provenance,
            "required_preservation_promises": slot_preservation,
            "required_verification_contracts": slot_verification,
            "dnt": _bounded_strings(dnt_texts, 8, 320),
            "prohibitions": _bounded_strings(prohibition_texts, 8, 320),
            "dnt_surface_ids": dnt_surface_ids,
            "prohibited_surface_ids": prohibited_surface_ids,
            "authority_refs": authority_refs,
            "evidence_refs": evidence_refs,
        }
        if separate:
            slot["separate_decision"] = True
        if not slot_req_ids:
            frame_errors.append(f"{slot['slot_id']}: required Source Requirement binding is missing")
        if not allowed_decisions:
            frame_errors.append(f"{slot['slot_id']}: allowed decision set is empty")
        if not allowed_targets:
            frame_errors.append(f"{slot['slot_id']}: allowed target set is empty")
        if surface.get("kind") == "OWNER" and not owner:
            frame_errors.append(f"{slot['slot_id']}: current owner authority is missing")
        slots.append(slot)

    explicit_preservation_required = any(
        isinstance(value, dict) and value.get("required_preservation_promises") not in (None, [], "")
        for value in (brain, source)
    )
    explicit_verification_required = any(
        isinstance(value, dict) and value.get("required_verification_contracts") not in (None, [], "")
        for value in (brain, source)
    )
    requirement_preservation_required = any(
        item.get("obligation_type") in {"PRESERVATION", "PROHIBITION"}
        for item in atomic_obligations
    )
    explicit_inherited_preservation = any(
        item.get("obligation_type") in {"PRESERVATION", "PROHIBITION"}
        and (
            item.get("inherited") is True
            or item.get("inherited_satisfaction") is True
        )
        for item in atomic_obligations
    )
    requirement_verification_required = any(
        item.get("obligation_type") == "TEST" for item in atomic_obligations
    )
    if not slots:
        frame_errors.append("required decision slots are missing")
    if not reqs:
        frame_errors.append("active Source Requirements are missing")
    if explicit_preservation_required and not any(_frame_text(item) for item in preservation_records):
        frame_errors.append("required preservation authority is unavailable")
    if explicit_verification_required and not any(_frame_text(item) for item in verification_records):
        frame_errors.append("required verification authority is unavailable")
    if (
        requirement_preservation_required
        and not any(slot.get("required_preservation_promises") for slot in slots)
        and not explicit_inherited_preservation
    ):
        frame_errors.append("required preservation authority could not be bound to a decision slot")
    if requirement_verification_required and not any(
        slot.get("required_verification_contracts") for slot in slots
    ):
        frame_errors.append("required verification authority could not be bound to a decision slot")
    registry_check = validate_canonical_surface_registry(registry_value, evidence)
    if not registry_check.get("valid"):
        frame_errors.extend(registry_check.get("errors", [])[:8])
    seed_check = validate_impact_seeds(raw_seeds, registry_value)
    if not seed_check.get("valid"):
        frame_errors.extend(seed_check.get("errors", [])[:8])
    if core_value and not validate_canonical_mandatory_planning_core(core_value).get("valid"):
        frame_errors.append("canonical mandatory planning core is invalid")
    frame_errors = list(dict.fromkeys(
        str(item) for item in frame_errors if str(item)
    ))[:24]
    frame = {
        "version": IMPACT_DECISION_FRAME_VERSION,
        "artifact_type": "ImpactDecisionFrame",
        "project_id": project_id,
        "task_id": task_id,
        "authority_change_authorized": bool(authority_change),
        "authority_change_targets": list(authority_targets if authority_change else []),
        "structured_obligation_binding": structured_obligation_binding,
        "source_planning_context_hash": str(context_hash),
        "source_mandatory_core_hash": str(core_hash),
        "requirement_obligation_ledger": copy.deepcopy(obligation_ledger_value),
        "decision_slots": slots,
        "frame_errors": frame_errors,
        "frame_complete": False,
        "frame_coverage_ready": False,
    }
    coverage = _build_frame_coverage(frame)
    if coverage.get("uncovered_obligations"):
        frame_errors.append(
            f"{IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP}: "
            + ", ".join(coverage.get("uncovered_obligations", []))
        )
    frame["impact_decision_frame_coverage"] = copy.deepcopy(coverage)
    frame["coverage"] = copy.deepcopy(coverage)
    frame["frame_errors"] = list(dict.fromkeys(
        str(item) for item in frame_errors if str(item)
    ))[:24]
    frame["frame_coverage_ready"] = (
        coverage.get("coverage_status") == IMPACT_FRAME_COVERAGE_READY
    )
    frame["frame_complete"] = not frame["frame_errors"] and frame["frame_coverage_ready"]
    frame["frame_hash"] = impact_decision_frame_hash(frame)
    return frame


def validate_impact_decision_frame(frame):
    """Validate frame integrity, authority, and pre-model coverage."""
    value = frame if isinstance(frame, dict) else {}
    errors = []
    if value.get("version") != IMPACT_DECISION_FRAME_VERSION:
        errors.append("unsupported ImpactDecisionFrame version")
    if value.get("artifact_type") != "ImpactDecisionFrame":
        errors.append("wrong ImpactDecisionFrame artifact type")
    if not value.get("source_planning_context_hash"):
        errors.append("source planning context hash is missing")
    if not value.get("source_mandatory_core_hash"):
        errors.append("source mandatory core hash is missing")
    if not value.get("project_id"):
        errors.append("project ID is missing")
    if not value.get("task_id"):
        errors.append("task ID is missing")
    if not isinstance(value.get("requirement_obligation_ledger"), dict):
        errors.append("requirement obligation ledger is missing")
    if not isinstance(value.get("frame_coverage_ready"), bool):
        errors.append("frame coverage readiness is missing")
    if value.get("frame_hash") != impact_decision_frame_hash(value):
        errors.append("ImpactDecisionFrame hash does not match canonical contents")
    slots = value.get("decision_slots")
    if not isinstance(slots, list) or not slots:
        errors.append("required decision slots are missing")
        slots = []
    frame_obligations = _atomic_obligation_records(
        value.get("requirement_obligation_ledger") or []
    )
    seen_slot_ids = set()
    seen_surfaces = {}
    for slot in slots[:MAX_IMPACT_SEEDS]:
        if not isinstance(slot, dict):
            errors.append("decision slot must be an object")
            continue
        slot_id = str(slot.get("slot_id") or "")
        if not slot_id or slot_id in seen_slot_ids:
            errors.append("decision slot IDs must be present and unique")
        seen_slot_ids.add(slot_id)
        surface_id = str(slot.get("surface_id") or "")
        if surface_id in seen_surfaces and not slot.get("separate_decision"):
            errors.append(f"{slot_id}: duplicate canonical surface requires explicit separate decision")
        seen_surfaces[surface_id] = slot_id
        for field in (
            "seed_id", "impact_id", "surface_id", "requirement_ids", "allowed_decisions",
            "candidate_obligation_ids", "surface_capabilities", "inherited_obligation_ids",
            "allowed_targets", "required_interfaces", "required_preservation_promises",
            "required_verification_contracts", "dnt", "prohibitions", "authority_refs",
            "dnt_surface_ids", "prohibited_surface_ids", "evidence_refs",
        ):
            raw = slot.get(field)
            if field in {"seed_id", "impact_id", "surface_id"} and not raw:
                errors.append(f"{slot_id or '<missing>'}: {field} is missing")
            if field not in {"seed_id", "impact_id", "surface_id"} and not isinstance(raw, list):
                errors.append(f"{slot_id or '<missing>'}: {field} must be a bounded list")
        if "structured_obligation_binding" in slot and not isinstance(
            slot.get("structured_obligation_binding"), bool
        ):
            errors.append(f"{slot_id or '<missing>'}: structured obligation binding must be boolean")
        for field in ("surface_kind", "surface_role", "surface_path", "surface_symbol"):
            if not isinstance(slot.get(field), str) or not slot.get(field):
                # Symbols may legitimately be empty for an entrypoint or
                # other evidence surface, but the derived path remains
                # mandatory authority.  Keep the old role/kind requirement
                # strict and validate symbol as a string.
                if field == "surface_symbol" and isinstance(slot.get(field), str):
                    continue
                errors.append(f"{slot_id or '<missing>'}: {field} is missing")
        if "surface_structured_relations" in slot and not isinstance(
            slot.get("surface_structured_relations"), list
        ):
            errors.append(f"{slot_id or '<missing>'}: surface structured relations must be a bounded list")
        for field in ("decision_capabilities", "obligations_satisfied_by_decision"):
            if not isinstance(slot.get(field), dict):
                errors.append(f"{slot_id or '<missing>'}: {field} must be an object")
        allowed = set(str(item) for item in slot.get("allowed_decisions", []) or [])
        unknown_decisions = allowed.difference(IMPACT_DECISION_CHOICES)
        if unknown_decisions:
            errors.append(f"{slot_id}: unknown allowed decision kind")
        if "NEW_OWNER" in allowed or "OWNER_MIGRATION" in allowed:
            errors.append(f"{slot_id}: forbidden ownership migration is exposed without explicit authority")
        if "AUTHORITY_CHANGE" in allowed and value.get("authority_change_authorized") is not True:
            errors.append(f"{slot_id}: authority change is not explicitly authorized")
        if "AUTHORITY_CHANGE" in allowed and str(slot.get("surface_kind")) != "OWNER" and str(
            slot.get("surface_role")
        ) not in {"OWNER", "STATE_OWNER", "INPUT_OWNER"}:
            errors.append(f"{slot_id}: authority change is not bound to an owner surface")
        if not allowed.intersection(IMPACT_DECISION_CHOICES):
            errors.append(f"{slot_id}: allowed decision set is empty")
        candidate_ids = {
            str(item) for item in slot.get("candidate_obligation_ids", []) or []
        }
        surface = {
            "surface_id": slot.get("surface_id"),
            "kind": slot.get("surface_kind"),
            "role": slot.get("surface_role"),
            "path": slot.get("surface_path"),
            "symbol": slot.get("surface_symbol"),
            "structured_relations": list(
                slot.get("surface_structured_relations", []) or []
            ),
        }
        if slot.get("surface_capabilities") != _surface_capabilities(surface):
            errors.append(f"{slot_id}: surface capability projection is not canonical")
        for decision in allowed.intersection(IMPACT_DECISION_CHOICES):
            expected_capabilities = _decision_capabilities(decision)
            actual_capabilities = slot.get("decision_capabilities", {}).get(decision)
            if actual_capabilities != expected_capabilities:
                errors.append(f"{slot_id}: decision capability projection is not canonical")
        expected_candidate_ids = [
            str(item.get("obligation_id")) for item in frame_obligations
            if item.get("obligation_id") and _frame_obligation_relevant(item, slot, surface)
        ]
        expected_inherited_ids = [
            str(item.get("obligation_id")) for item in frame_obligations
            if item.get("obligation_id") and _frame_inherited_obligation(item, slot)
        ]
        if candidate_ids != set(expected_candidate_ids):
            errors.append(f"{slot_id}: candidate obligation projection is not canonical")
        if set(str(item) for item in slot.get("inherited_obligation_ids", []) or []) != set(
            expected_inherited_ids
        ):
            errors.append(f"{slot_id}: inherited obligation projection is not canonical")
        actual_mapping = slot.get("obligations_satisfied_by_decision", {})
        expected_mapping = {
            str(decision): [
                str(item.get("obligation_id")) for item in frame_obligations
                if item.get("obligation_id") and _frame_decision_satisfies_obligation(
                    item, slot, decision, surface,
                )
            ] for decision in slot.get("allowed_decisions", []) or []
        }
        if actual_mapping != expected_mapping:
            errors.append(f"{slot_id}: obligation decision capability projection is not canonical")
        targets = [str(item) for item in slot.get("allowed_targets", []) or []]
        if not targets or str(slot.get("surface_id")) not in targets:
            errors.append(f"{slot_id}: target authority is not bound to its canonical surface")
        for obligation_field in ("required_preservation_promises", "required_verification_contracts"):
            for obligation in slot.get(obligation_field, []) or []:
                if not isinstance(obligation, dict) or not obligation.get("text") or not obligation.get("obligation_id"):
                    errors.append(f"{slot_id}: malformed {obligation_field}")
    frame_errors = [str(item) for item in list(value.get("frame_errors", []) or [])]
    errors.extend(frame_errors)
    coverage_check = validate_impact_decision_frame_coverage(value)
    if not coverage_check.get("valid"):
        for item in coverage_check.get("errors", [])[:8]:
            if str(item) not in errors:
                errors.append(str(item))
    errors = list(dict.fromkeys(errors))[:32]
    incomplete = bool(errors) or value.get("frame_complete") is not True
    coverage_gap = (
        coverage_check.get("status") == IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP
        and not any(
            str(item).startswith("required ") and " authority is unavailable" in str(item)
            for item in errors
        )
        and any(
            item.get("obligation_type") == "BEHAVIOR_CHANGE"
            and not item.get("coverage_ready")
            for item in list((coverage_check.get("coverage") or {}).get("obligations", []) or [])
            if isinstance(item, dict)
        )
    )
    status = (
        IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP if coverage_gap
        else ("READY" if not incomplete else IMPACT_DECISION_FRAME_INCOMPLETE)
    )
    return {
        "valid": not incomplete,
        "status": status,
        "errors": errors if errors else [],
        "slot_count": len(slots),
        "required_slot_ids": [str(item.get("slot_id")) for item in slots if isinstance(item, dict)],
        "model_calls": 0,
        "frame_hash": value.get("frame_hash"),
        "coverage": copy.deepcopy(coverage_check.get("coverage", {})),
        "uncovered_obligations": list(coverage_check.get("uncovered_obligations", [])),
        "covered_obligations": int(coverage_check.get("covered_obligations", 0) or 0),
        "obligations_total": int(coverage_check.get("obligations_total", 0) or 0),
        "coverage_status": coverage_check.get("status"),
        "coverage_hash": coverage_check.get("coverage_hash"),
    }


validate_impact_decision_frame_artifact = validate_impact_decision_frame


def _impact_decision_frame_payload(frame):
    value = frame if isinstance(frame, dict) else {}

    def compact_obligation(item):
        if not isinstance(item, dict):
            return {"obligation_id": "", "text": _compact(item, 220)}
        # Requirement/evidence refs remain in the immutable local frame.  The
        # provider only needs the bounded obligation text and its stable local
        # label to understand what is fixed; repeating every provenance ref in
        # every slot recreates the V24.2 context burden.
        return {
            "obligation_id": str(item.get("obligation_id") or ""),
            "text": _compact(item.get("text"), 220),
        }

    def compact_slot(slot):
        owner = slot.get("current_owner")
        compact_owner = None
        if isinstance(owner, dict):
            compact_owner = {
                "surface_id": owner.get("surface_id"),
                "symbol": _compact(owner.get("symbol"), 120),
            }
        interfaces = []
        for item in list(slot.get("interface_provenance", []) or [])[:6]:
            if not isinstance(item, dict):
                continue
            interfaces.append({
                "surface_id": item.get("surface_id"),
                "symbol": _compact(item.get("symbol"), 140),
            })
        return {
            "slot_id": slot.get("slot_id"),
            "surface_id": slot.get("surface_id"),
            "allowed_decisions": list(slot.get("allowed_decisions", []) or []),
            "candidate_obligation_ids": list(slot.get("candidate_obligation_ids", []) or []),
            "surface_capabilities": list(slot.get("surface_capabilities", []) or []),
            "decision_capabilities": copy.deepcopy(slot.get("decision_capabilities", {})),
            "obligations_satisfied_by_decision": copy.deepcopy(
                slot.get("obligations_satisfied_by_decision", {})
            ),
            "inherited_obligation_ids": list(slot.get("inherited_obligation_ids", []) or []),
            "allowed_targets": list(slot.get("allowed_targets", []) or []),
            "authority_change_targets": list(slot.get("authority_change_targets", []) or []),
            "current_owner": compact_owner,
            "required_interfaces": list(slot.get("required_interfaces", []) or []),
            "interface_provenance": interfaces,
            "required_preservation_promises": [
                compact_obligation(item)
                for item in list(slot.get("required_preservation_promises", []) or [])[:8]
            ],
            "required_verification_contracts": [
                compact_obligation(item)
                for item in list(slot.get("required_verification_contracts", []) or [])[:8]
            ],
            "dnt": _bounded_strings(slot.get("dnt"), 6, 220),
            "prohibitions": _bounded_strings(slot.get("prohibitions"), 6, 220),
        }

    return {
        "version": 1,
        "artifact_type": "ImpactDecisionChoiceRequest",
        "project_id": value.get("project_id"),
        "task_id": value.get("task_id"),
        "source_planning_context_hash": value.get("source_planning_context_hash"),
        "source_mandatory_core_hash": value.get("source_mandatory_core_hash"),
        "impact_decision_frame_hash": value.get("frame_hash"),
        "what_is_fixed": [
            "slot identity", "surface identity", "current ownership", "required interfaces",
            "preservation obligations", "verification obligations", "DNT", "prohibitions",
        ],
        "what_must_be_decided": [
            "one decision per slot", "one authorized target per slot", "reason_code", "bounded_rationale",
        ],
        "what_must_not_be_repeated": [
            "impact IDs", "seed IDs", "surface IDs", "owners", "preservation_promises",
            "verification_contracts", "DNT", "prohibitions", "repository paths", "repository evidence",
        ],
        "active_obligations": [
            {
                "obligation_id": item.get("obligation_id"),
                "requirement_id": item.get("requirement_id"),
                "obligation_type": item.get("obligation_type"),
                "meaning": _compact(item.get("meaning") or item.get("text"), 220),
                "inherited_satisfaction": bool(item.get("inherited_satisfaction")),
            }
            for item in list(
                ((value.get("impact_decision_frame_coverage") or {}).get("obligations", []))
                or []
            )[:MAX_IMPACT_SEEDS * 2]
            if isinstance(item, dict)
        ],
        "decision_slots": [
            compact_slot(item) for item in list(value.get("decision_slots", []) or [])
            if isinstance(item, dict)
        ],
        "response_bounds": {
            "required_slot_count": len(value.get("decision_slots", []) or []),
            "exactly_one_choice_per_slot": True,
            "model_owned_fields": list(IMPACT_DECISION_MODEL_FIELDS),
        },
    }


def _projection_relative_path(path):
    """Return a safe project-relative path for the model-facing projection."""
    value = _normal_path(path)
    while value.startswith("./"):
        value = value[2:]
    if re.match(r"^[A-Za-z]:/", value):
        # The canonical frame should already contain project-relative paths.
        # If an older caller supplied an absolute path, retain only the
        # repository-looking suffix rather than leaking a machine path.
        lowered = value.casefold()
        for marker in ("src/", "tests/"):
            position = lowered.find(marker)
            if position >= 0:
                return value[position:]
        return value[3:].lstrip("/")
    return value.lstrip("/")


def _projection_alias(identifier):
    """Create a readable compact alias without hiding the canonical ID."""
    value = str(identifier or "")
    match = re.match(r"^(SLOT|SURF)-0*(\d+)$", value, re.IGNORECASE)
    if match:
        return f"{match.group(1).upper()}-{int(match.group(2))}"
    return value


def _projection_surface_from_slot(slot):
    value = slot if isinstance(slot, dict) else {}
    return {
        "surface_id": value.get("surface_id"),
        "kind": value.get("surface_kind"),
        "role": value.get("surface_role"),
        "path": value.get("surface_path"),
        "symbol": value.get("surface_symbol"),
        "structured_relations": list(value.get("surface_structured_relations", []) or []),
    }


def _projection_frame_obligations(frame):
    value = frame if isinstance(frame, dict) else {}
    coverage = value.get("impact_decision_frame_coverage")
    if not isinstance(coverage, dict):
        coverage = _build_frame_coverage(value)
    atomic_by_id = {
        str(item.get("obligation_id")): item
        for item in _atomic_obligation_records(value.get("requirement_obligation_ledger", {}))
        if isinstance(item, dict) and item.get("obligation_id")
    }
    return [
        {
            **copy.deepcopy(atomic_by_id.get(str(item.get("obligation_id")), {})),
            **copy.deepcopy(item),
        }
        for item in list(coverage.get("obligations", []) or [])
        if isinstance(item, dict) and item.get("obligation_id")
    ]


def _projection_required_obligation_details(frame, slot):
    """Derive model-required responsibility from the canonical frame only."""
    value = frame if isinstance(frame, dict) else {}
    slot_value = slot if isinstance(slot, dict) else {}
    surface = _projection_surface_from_slot(slot_value)
    inherited_on_slot = {
        str(item) for item in slot_value.get("inherited_obligation_ids", []) or []
    }
    required = []
    candidate_decisions = {}
    for obligation in _projection_frame_obligations(value):
        obligation_id = str(obligation.get("obligation_id") or "")
        if not obligation_id or obligation.get("inherited_satisfaction"):
            continue
        if obligation_id in inherited_on_slot:
            continue
        satisfying = []
        for decision in list(slot_value.get("allowed_decisions", []) or []):
            decision_name = str(decision)
            if _frame_decision_satisfies_obligation(
                obligation, slot_value, decision_name, surface,
            ):
                satisfying.append(decision_name)
        if satisfying:
            required.append(obligation_id)
            candidate_decisions[obligation_id] = satisfying
    return list(dict.fromkeys(required)), candidate_decisions


def classify_impact_decision_slots(frame):
    """Classify every full-frame slot without selecting a decision.

    The classification is a deterministic responsibility taxonomy.  It is
    deliberately separate from authority: the full frame remains the only
    source used to decide whether a choice is allowed.
    """
    value = frame if isinstance(frame, dict) else {}
    obligations = _projection_frame_obligations(value)
    by_obligation = {
        str(item.get("obligation_id")): item for item in obligations
    }
    result = []
    for slot in list(value.get("decision_slots", []) or []):
        if not isinstance(slot, dict) or not slot.get("slot_id"):
            continue
        required_ids, required_decisions = _projection_required_obligation_details(
            value, slot,
        )
        inherited_ids = [
            str(item) for item in list(slot.get("inherited_obligation_ids", []) or [])
            if str(item) in by_obligation
        ]
        candidate_ids = [
            str(item) for item in list(slot.get("candidate_obligation_ids", []) or [])
            if str(item) in by_obligation
        ]
        kind = str(slot.get("surface_kind") or "").upper()
        role = str(slot.get("surface_role") or "").upper()
        if required_ids:
            classification = "MODEL_CHOICE_REQUIRED"
            reason = "an active non-inherited obligation has a satisfying allowed decision"
        elif inherited_ids:
            classification = "DETERMINISTIC_INHERITED_ONLY"
            reason = "the slot contributes only inherited current-state obligations"
        elif kind == "TEST" or role == "CURRENT_TEST":
            classification = "EVIDENCE_ONLY"
            reason = "current test evidence is context and no explicit TEST obligation requires a choice"
        else:
            classification = "MODEL_CHOICE_SUPPORT"
            reason = "the slot is retained as bounded support context without a required model choice"
        all_decision_kinds = [
            str(item) for item in list(slot.get("allowed_decisions", []) or [])
        ]
        result.append({
            "slot_id": str(slot.get("slot_id")),
            "slot_alias": _projection_alias(slot.get("slot_id")),
            "surface_id": str(slot.get("surface_id") or ""),
            "surface_alias": _projection_alias(slot.get("surface_id")),
            "surface_kind": str(slot.get("surface_kind") or ""),
            "surface_role": str(slot.get("surface_role") or ""),
            "surface_path": _projection_relative_path(slot.get("surface_path")),
            "classification": classification,
            "choice_required": classification == "MODEL_CHOICE_REQUIRED",
            "reason": reason,
            "required_obligation_ids": list(required_ids),
            "required_decision_kinds": list(dict.fromkeys(
                decision for obligation_id in required_ids
                for decision in required_decisions.get(obligation_id, [])
            )),
            "candidate_obligation_ids": list(candidate_ids),
            "candidate_decision_kinds": all_decision_kinds,
            "inherited_obligation_ids": list(dict.fromkeys(inherited_ids)),
            "dnt_targeted": _frame_surface_is_forbidden(
                _projection_surface_from_slot(slot), slot,
            ),
            "prohibited": _frame_surface_is_forbidden(
                _projection_surface_from_slot(slot), slot,
            ),
            "dnt_status": (
                "DNT_PROHIBITED"
                if _frame_surface_is_forbidden(_projection_surface_from_slot(slot), slot)
                else "NOT_DNT"
            ),
        })
    return result


def _projection_constraint_records(frame):
    """Fan shared constraints in once while retaining all source fan-in."""
    value = frame if isinstance(frame, dict) else {}
    grouped = {}
    for slot in list(value.get("decision_slots", []) or []):
        if not isinstance(slot, dict) or not slot.get("slot_id"):
            continue
        slot_id = str(slot.get("slot_id"))
        surface_id = str(slot.get("surface_id") or "")
        values = []
        for text in list(slot.get("dnt", []) or []):
            values.append(("DNT", text))
        for text in list(slot.get("prohibitions", []) or []):
            values.append(("PROHIBITION", text))
        for item in list(slot.get("required_preservation_promises", []) or []):
            if isinstance(item, dict):
                values.append(("PRESERVATION", item.get("text") or item.get("meaning")))
        for constraint_type, text in values:
            text = _compact(text, 280)
            if not text:
                continue
            key = _core_normalize_text(text)
            entry = grouped.setdefault(key, {
                "text": text,
                "constraint_types": [],
                "slot_ids": [],
                "surface_ids": [],
                "authority_refs": [],
                "evidence_refs": [],
            })
            if constraint_type not in entry["constraint_types"]:
                entry["constraint_types"].append(constraint_type)
            if slot_id not in entry["slot_ids"]:
                entry["slot_ids"].append(slot_id)
            if surface_id and surface_id not in entry["surface_ids"]:
                entry["surface_ids"].append(surface_id)
            for ref in list(slot.get("authority_refs", []) or []):
                if str(ref) and str(ref) not in entry["authority_refs"]:
                    entry["authority_refs"].append(str(ref))
            for ref in list(slot.get("evidence_refs", []) or []):
                if str(ref) and str(ref) not in entry["evidence_refs"]:
                    entry["evidence_refs"].append(str(ref))
    result = []
    for index, item in enumerate(sorted(grouped.values(), key=lambda value: (
        _core_normalize_text(value.get("text")),
        ",".join(value.get("constraint_types", [])),
    )), 1):
        prefix = "DNT" if "DNT" in item["constraint_types"] else "FIXED"
        result.append({
            "constraint_id": f"{prefix}-{index:03d}",
            "alias": f"{prefix}-{index:03d}",
            "text": item["text"],
            "constraint_types": list(item["constraint_types"]),
            "slot_ids": list(item["slot_ids"]),
            "surface_ids": list(item["surface_ids"]),
            "authority_refs": _bounded_ids(item["authority_refs"], 32),
            "evidence_refs": _bounded_ids(item["evidence_refs"], MAX_EVIDENCE_REFS_PER_IMPACT),
        })
    return result


def _projection_constraint_aliases(constraints, slot_id):
    return [
        str(item.get("alias")) for item in constraints
        if str(slot_id) in {str(value) for value in item.get("slot_ids", []) or []}
    ]


def _projection_compact_obligation(obligation):
    value = obligation if isinstance(obligation, dict) else {}
    return {
        "obligation_id": str(value.get("obligation_id") or ""),
        "requirement_id": str(value.get("requirement_id") or ""),
        "obligation_type": str(value.get("obligation_type") or ""),
        "meaning": _compact(value.get("meaning") or value.get("text"), 240),
        "inherited_satisfaction": bool(value.get("inherited_satisfaction")),
        "candidate_slot_ids": [str(item) for item in list(value.get("candidate_slots", []) or [])],
        "candidate_decision_kinds": [str(item) for item in list(value.get("candidate_decisions", []) or [])],
    }


def _projection_model_payload(frame, classifications, constraints, obligations):
    value = frame if isinstance(frame, dict) else {}
    required = [
        item for item in classifications
        if item.get("classification") == "MODEL_CHOICE_REQUIRED"
    ]
    required_ids = [str(item.get("slot_id")) for item in required]
    model_slots = []
    support_context = []
    full_slots = {
        str(item.get("slot_id")): item for item in value.get("decision_slots", [])
        if isinstance(item, dict) and item.get("slot_id")
    }
    for classification in classifications:
        slot_id = str(classification.get("slot_id"))
        slot = full_slots.get(slot_id, {})
        constraint_aliases = _projection_constraint_aliases(constraints, slot_id)
        if classification.get("classification") == "MODEL_CHOICE_REQUIRED":
            required_obligations = set(
                str(item) for item in classification.get("required_obligation_ids", []) or []
            )
            mapping = {}
            for decision in list(slot.get("allowed_decisions", []) or []):
                decision = str(decision)
                selected = [
                    str(item) for item in list(
                        (slot.get("obligations_satisfied_by_decision", {}) or {}).get(decision, [])
                        or []
                    ) if str(item) in required_obligations
                ]
                if selected:
                    mapping[decision] = selected
            model_slots.append({
                "slot_id": slot_id,
                "slot_alias": _projection_alias(slot_id),
                "surface_id": str(slot.get("surface_id") or ""),
                "surface_alias": _projection_alias(slot.get("surface_id")),
                "surface_role": str(slot.get("surface_role") or ""),
                "surface_path": _projection_relative_path(slot.get("surface_path")),
                "surface_capabilities": list(slot.get("surface_capabilities", []) or []),
                "allowed_decisions": [str(item) for item in list(slot.get("allowed_decisions", []) or [])],
                "decision_capabilities": {
                    str(decision): list(
                        (slot.get("decision_capabilities", {}) or {}).get(str(decision))
                        or _decision_capabilities(decision)
                    ) for decision in list(slot.get("allowed_decisions", []) or [])
                },
                "obligation_ids": list(classification.get("required_obligation_ids", []) or []),
                "obligations_satisfied_by_decision": mapping,
                "allowed_targets": [str(item) for item in list(slot.get("allowed_targets", []) or [])],
                "constraint_aliases": constraint_aliases,
                "dnt_status": classification.get("dnt_status"),
            })
        else:
            # Support and evidence are context only.  They are never included
            # in the response contract and therefore cannot become writable
            # merely because they are visible to the model.
            support_context.append({
                "slot_id": slot_id,
                "slot_alias": _projection_alias(slot_id),
                "surface_id": str(slot.get("surface_id") or ""),
                "surface_alias": _projection_alias(slot.get("surface_id")),
                "surface_role": str(slot.get("surface_role") or ""),
                "surface_path": _projection_relative_path(slot.get("surface_path")),
                "classification": classification.get("classification"),
                "inherited_obligation_ids": list(classification.get("inherited_obligation_ids", []) or []),
                "candidate_obligation_ids": list(classification.get("candidate_obligation_ids", []) or []),
                "constraint_aliases": constraint_aliases,
            })
    active = [_projection_compact_obligation(item) for item in obligations]
    return {
        "version": 1,
        "artifact_type": "DecisionRelevantImpactChoiceRequest",
        "source_frame_hash": value.get("frame_hash"),
        "source_planning_context_hash": value.get("source_planning_context_hash"),
        "source_mandatory_core_hash": value.get("source_mandatory_core_hash"),
        "active_obligations": active,
        "required_choice_slots": model_slots,
        "required_choice_slot_ids": required_ids,
        "support_context": support_context,
        "fixed_constraints": [
            {
                "alias": str(item.get("alias")),
                "constraint_types": list(item.get("constraint_types", []) or []),
                "text": _compact(item.get("text"), 280),
            }
            for item in constraints
        ],
        "response_bounds": {
            "required_slot_count": len(required_ids),
            "required_choice_slot_ids": required_ids,
            "exactly_one_choice_per_required_slot": True,
            "excluded_slot_policy": "returning an excluded slot is invalid",
            "model_owned_fields": list(IMPACT_DECISION_MODEL_FIELDS),
        },
        "authority_boundary": (
            "The full ImpactDecisionFrame remains authoritative; this is a read-only choice projection."
        ),
    }


def build_decision_relevant_impact_choice_projection(frame):
    """Build the immutable V24.4.3 model-choice projection from a full frame."""
    value = copy.deepcopy(frame if isinstance(frame, dict) else {})
    obligations = _projection_frame_obligations(value)
    classifications = classify_impact_decision_slots(value)
    constraints = _projection_constraint_records(value)
    full_slots = {
        str(item.get("slot_id")): item for item in list(value.get("decision_slots", []) or [])
        if isinstance(item, dict) and item.get("slot_id")
    }
    slot_provenance = {}
    for classification in classifications:
        slot_id = str(classification.get("slot_id"))
        slot = full_slots.get(slot_id, {})
        slot_provenance[slot_id] = {
            "slot_id": slot_id,
            "seed_id": str(slot.get("seed_id") or ""),
            "impact_id": str(slot.get("impact_id") or ""),
            "surface_id": str(slot.get("surface_id") or ""),
            "surface_role": str(slot.get("surface_role") or ""),
            "surface_path": _projection_relative_path(slot.get("surface_path")),
            "classification": classification.get("classification"),
            "allowed_decisions": [str(item) for item in list(slot.get("allowed_decisions", []) or [])],
            "allowed_targets": [str(item) for item in list(slot.get("allowed_targets", []) or [])],
            "decision_capabilities": copy.deepcopy(slot.get("decision_capabilities", {})),
            "candidate_obligation_ids": [str(item) for item in list(slot.get("candidate_obligation_ids", []) or [])],
            "inherited_obligation_ids": [str(item) for item in list(slot.get("inherited_obligation_ids", []) or [])],
            "obligations_satisfied_by_decision": copy.deepcopy(
                slot.get("obligations_satisfied_by_decision", {})
            ),
            "current_owner": copy.deepcopy(slot.get("current_owner")),
            "required_interfaces": [str(item) for item in list(slot.get("required_interfaces", []) or [])],
            "required_preservation_promises": copy.deepcopy(
                slot.get("required_preservation_promises", [])
            ),
            "required_verification_contracts": copy.deepcopy(
                slot.get("required_verification_contracts", [])
            ),
            "dnt": list(slot.get("dnt", []) or []),
            "prohibitions": list(slot.get("prohibitions", []) or []),
            "dnt_surface_ids": [str(item) for item in list(slot.get("dnt_surface_ids", []) or [])],
            "prohibited_surface_ids": [str(item) for item in list(slot.get("prohibited_surface_ids", []) or [])],
            "authority_refs": [str(item) for item in list(slot.get("authority_refs", []) or [])],
            "evidence_refs": [str(item) for item in list(slot.get("evidence_refs", []) or [])],
            "source_frame_hash": value.get("frame_hash"),
        }
    obligation_provenance = {
        str(item.get("obligation_id")): {
            **_projection_compact_obligation(item),
            "inherited_slots": [str(value) for value in list(item.get("inherited_slots", []) or [])],
            "satisfied_by_decision": copy.deepcopy(item.get("satisfied_by_decision", {})),
            "evidence_refs": [str(value) for value in list(item.get("evidence_refs", []) or [])],
            "coverage_ready": bool(item.get("coverage_ready")),
        }
        for item in obligations
    }
    constraint_provenance = {
        str(item.get("alias")): copy.deepcopy(item) for item in constraints
    }
    aliases = {
        _projection_alias(slot_id): slot_id for slot_id in slot_provenance
    }
    aliases.update({
        f"OBL-{index:03d}": obligation_id
        for index, obligation_id in enumerate(obligation_provenance, 1)
    })
    aliases.update({
        str(item.get("alias")): str(item.get("constraint_id"))
        for item in constraints
    })
    required_obligation_ids = list(dict.fromkeys(
        str(value) for item in classifications
        if item.get("classification") == "MODEL_CHOICE_REQUIRED"
        for value in item.get("required_obligation_ids", []) or []
    ))
    required_ids = [
        str(item.get("slot_id")) for item in classifications
        if item.get("classification") == "MODEL_CHOICE_REQUIRED"
    ]
    represented_obligation_ids = set(required_obligation_ids)
    model_choice_coverage = [
        {
            "obligation_id": str(item.get("obligation_id")),
            "inherited": bool(item.get("inherited_satisfaction")),
            "model_choice_required": str(item.get("obligation_id")) in set(required_obligation_ids),
            "model_choice_represented": (
                bool(item.get("inherited_satisfaction"))
                or str(item.get("obligation_id")) in represented_obligation_ids
            ),
        }
        for item in obligations
    ]
    model_choice_rate = (
        sum(item["model_choice_represented"] for item in model_choice_coverage)
        / len(model_choice_coverage) if model_choice_coverage else 1.0
    )
    full_reachable = bool(
        len(slot_provenance) == len(full_slots)
        and len(obligation_provenance) == len(obligations)
        and all(item.get("source_frame_hash") == value.get("frame_hash") for item in slot_provenance.values())
    )
    model_payload = _projection_model_payload(
        value, classifications, constraints, obligations,
    )
    projection = {
        "version": DECISION_RELEVANT_IMPACT_CHOICE_PROJECTION_VERSION,
        "artifact_type": "DecisionRelevantImpactChoiceProjection",
        "source_frame_hash": value.get("frame_hash"),
        "source_frame_version": value.get("version"),
        "source_planning_context_hash": value.get("source_planning_context_hash"),
        "source_mandatory_core_hash": value.get("source_mandatory_core_hash"),
        "required_choice_slot_ids": [
            str(item.get("slot_id")) for item in classifications
            if item.get("classification") == "MODEL_CHOICE_REQUIRED"
        ],
        "excluded_choice_slot_ids": [
            str(item.get("slot_id")) for item in classifications
            if item.get("classification") != "MODEL_CHOICE_REQUIRED"
        ],
        "slot_classification": classifications,
        "fixed_constraints": constraints,
        "support_context": model_payload.get("support_context", []),
        "provenance_map": {
            "source_frame": {
                "frame_hash": value.get("frame_hash"),
                "frame_version": value.get("version"),
                "artifact_type": value.get("artifact_type"),
                "authoritative_fields": [
                    "decision_slots", "requirement_obligation_ledger",
                    "impact_decision_frame_coverage", "frame_hash",
                ],
            },
            "aliases": aliases,
            "slots": slot_provenance,
            "obligations": obligation_provenance,
            "constraints": constraint_provenance,
        },
        "model_payload": model_payload,
        "model_choice_semantic_coverage": model_choice_rate,
        "full_authority_provenance_coverage": 1.0 if full_reachable else 0.0,
        "required_model_choice_slots_total": len(required_ids),
        "required_model_choice_slots_rendered": len(required_ids),
        "required_model_choice_slot_coverage_rate": 1.0 if required_ids else 1.0,
        "full_frame_semantic_coverage": 1.0 if full_reachable else 0.0,
        "full_provenance_reachable": 1.0 if full_reachable else 0.0,
        "projection_semantic_coverage": {
            "obligations": model_choice_coverage,
            "model_choice_rate": model_choice_rate,
            "full_frame_reachable": full_reachable,
            "full_frame_slot_count": len(full_slots),
            "full_frame_obligation_count": len(obligations),
        },
        "response_contract": copy.deepcopy(model_payload.get("response_bounds", {})),
        "metrics": {
            "impact_frame_slots_total": len(full_slots),
            "impact_model_choice_slots_required": len(
                [item for item in classifications if item.get("classification") == "MODEL_CHOICE_REQUIRED"]
            ),
            "impact_slots_inherited_only": len(
                [item for item in classifications if item.get("classification") == "DETERMINISTIC_INHERITED_ONLY"]
            ),
            "impact_slots_evidence_only": len(
                [item for item in classifications if item.get("classification") == "EVIDENCE_ONLY"]
            ),
            "impact_choice_projection_chars": len(_compact_json(model_payload)),
            "impact_choice_projection_semantic_coverage": model_choice_rate,
        },
    }
    projection["projection_hash"] = decision_relevant_impact_choice_projection_hash(projection)
    return projection


build_impact_decision_choice_projection = build_decision_relevant_impact_choice_projection
build_impact_choice_projection = build_decision_relevant_impact_choice_projection


def decision_relevant_impact_choice_projection_hash(projection):
    value = copy.deepcopy(projection if isinstance(projection, dict) else {})
    value.pop("projection_hash", None)
    return _impact_decision_hash(value)


impact_choice_projection_hash = decision_relevant_impact_choice_projection_hash


def validate_decision_relevant_impact_choice_projection(projection, frame):
    """Validate projection integrity against the authoritative full frame."""
    value = projection if isinstance(projection, dict) else {}
    errors = []
    source = frame if isinstance(frame, dict) else {}
    frame_check = validate_impact_decision_frame(source)
    if not frame_check.get("valid"):
        errors.append(IMPACT_DECISION_FRAME_INCOMPLETE)
    expected = build_decision_relevant_impact_choice_projection(source)
    if value.get("artifact_type") != expected.get("artifact_type"):
        errors.append(IMPACT_DECISION_PROJECTION_INVALID)
    if value.get("version") != expected.get("version"):
        errors.append(IMPACT_DECISION_PROJECTION_INVALID)
    if value.get("source_frame_hash") != source.get("frame_hash"):
        errors.append(IMPACT_DECISION_PROJECTION_INVALID + ": source frame hash")
    if value.get("projection_hash") != decision_relevant_impact_choice_projection_hash(value):
        errors.append(IMPACT_DECISION_PROJECTION_INVALID + ": projection hash")
    for field in (
        "source_frame_version", "source_planning_context_hash", "source_mandatory_core_hash",
        "required_choice_slot_ids", "excluded_choice_slot_ids", "slot_classification",
        "fixed_constraints", "support_context", "provenance_map", "model_payload",
        "response_contract", "projection_semantic_coverage", "metrics",
        "model_choice_semantic_coverage", "full_authority_provenance_coverage",
        "required_model_choice_slots_total", "required_model_choice_slots_rendered",
        "required_model_choice_slot_coverage_rate", "full_frame_semantic_coverage",
        "full_provenance_reachable",
    ):
        if value.get(field) != expected.get(field):
            errors.append(IMPACT_DECISION_PROJECTION_INVALID + f": {field}")
    required_ids = [
        str(item.get("slot_id")) for item in list(value.get("slot_classification", []) or [])
        if isinstance(item, dict) and item.get("classification") == "MODEL_CHOICE_REQUIRED"
    ]
    if required_ids != list(value.get("required_choice_slot_ids", []) or []):
        errors.append(IMPACT_DECISION_PROJECTION_INVALID + ": required choice slot cardinality")
    model_payload = value.get("model_payload")
    model_payload = model_payload if isinstance(model_payload, dict) else {}
    response = model_payload.get("response_bounds", {})
    if response.get("required_slot_count") != len(required_ids):
        errors.append(IMPACT_DECISION_PROJECTION_INVALID + ": response bounds")
    return {
        "valid": not errors,
        "status": "READY" if not errors else IMPACT_DECISION_PROJECTION_INVALID,
        "errors": list(dict.fromkeys(errors)),
        "required_choice_slot_ids": list(value.get("required_choice_slot_ids", []) or []),
        "excluded_choice_slot_ids": list(value.get("excluded_choice_slot_ids", []) or []),
        "slot_count": len(list(value.get("slot_classification", []) or [])),
        "model_choice_semantic_coverage": value.get("model_choice_semantic_coverage", 0.0),
        "full_authority_provenance_coverage": value.get("full_authority_provenance_coverage", 0.0),
        "required_model_choice_slots_total": value.get(
            "required_model_choice_slots_total", 0,
        ),
        "required_model_choice_slots_rendered": value.get(
            "required_model_choice_slots_rendered", 0,
        ),
        "required_model_choice_slot_coverage_rate": value.get(
            "required_model_choice_slot_coverage_rate", 0.0,
        ),
        "full_frame_semantic_coverage": value.get(
            "full_frame_semantic_coverage", 0.0,
        ),
        "full_provenance_reachable": value.get("full_provenance_reachable", 0.0),
        "coverage": copy.deepcopy(value.get("projection_semantic_coverage", {})),
        "projection_hash": value.get("projection_hash"),
        "model_calls": 0,
    }


validate_impact_decision_choice_projection = validate_decision_relevant_impact_choice_projection
validate_impact_choice_projection = validate_decision_relevant_impact_choice_projection


def audit_impact_decision_frame_model_payload(frame, payload=None, rendered=None):
    """Audit the pre-V24.4.3 full-slot payload before compacting it."""
    value = payload if isinstance(payload, dict) else _impact_decision_frame_payload(frame)
    serialized = _compact_json(value)
    rendered_text = rendered if isinstance(rendered, str) else serialized
    slots = [item for item in list(value.get("decision_slots", []) or []) if isinstance(item, dict)]

    def fragment_chars(keys, source=None):
        source_value = source if isinstance(source, dict) else value
        return len(_compact_json({key: source_value.get(key) for key in keys if key in source_value}))

    slot_categories = {
        "surface_identities": ("slot_id", "surface_id"),
        "slot_identities": ("slot_id",),
        "allowed_decisions": ("allowed_decisions",),
        "decision_capabilities": ("decision_capabilities",),
        "obligation_mappings": (
            "candidate_obligation_ids", "obligations_satisfied_by_decision",
        ),
        "inherited_obligations": ("inherited_obligation_ids",),
        "authority_metadata": (
            "allowed_targets", "authority_change_targets", "current_owner",
            "required_interfaces", "interface_provenance",
        ),
        "authority_change_metadata": ("authority_change_targets",),
        "preservation_promises": ("required_preservation_promises",),
        "verification_contracts": ("required_verification_contracts",),
        "dnt_prohibitions": ("dnt", "prohibitions"),
        "paths_and_surface_roles": (),
        "provenance_refs": (),
        "evidence_refs": (),
        "absolute_paths": (),
        "source_hashes": (),
    }
    contributions = {
        "role_envelope_instructions": max(0, len(rendered_text) - len(serialized)),
        "atomic_obligations": fragment_chars(("active_obligations",)),
        "response_schema_and_bounds": fragment_chars(("response_bounds",)),
        "response_schema_example": fragment_chars(("response_bounds",)),
    }
    for category, keys in slot_categories.items():
        if category == "provenance_refs":
            contributions[category] = 0
            continue
        if category == "evidence_refs":
            contributions[category] = 0
            continue
        if category == "absolute_paths":
            contributions[category] = 0
            continue
        if category == "source_hashes":
            contributions[category] = fragment_chars(
                ("source_planning_context_hash", "source_mandatory_core_hash",
                 "impact_decision_frame_hash"),
            )
            continue
        contributions[category] = sum(fragment_chars(keys, slot) for slot in slots)
    repeated_constraints = {}
    for slot in slots:
        for field in ("dnt", "prohibitions"):
            for text in list(slot.get(field, []) or []):
                normalized = _core_normalize_text(text)
                if normalized:
                    repeated_constraints.setdefault(normalized, {"text": str(text), "occurrences": 0})
                    repeated_constraints[normalized]["occurrences"] += 1
    repeated = [item for item in repeated_constraints.values() if item["occurrences"] > 1]
    contributions["repeated_constraints"] = sum(
        len(_compact_json(item)) for item in repeated
    )
    return {
        "artifact_type": "ImpactDecisionFramePayloadAudit",
        "representation": "V24.4.2_FULL_SLOT_PAYLOAD",
        "payload_chars": len(serialized),
        "serialized_payload_chars": len(serialized),
        "rendered_chars": len(rendered_text),
        "role_envelope_instruction_chars": contributions["role_envelope_instructions"],
        "category_contributions": contributions,
        "repeated_constraint_records": repeated,
        "decision_slot_count": len(slots),
        "model_choice_cardinality": len(slots),
        "model_calls": 0,
    }


audit_impact_decision_payload = audit_impact_decision_frame_model_payload
audit_legacy_impact_decision_payload = audit_impact_decision_frame_model_payload


def build_impact_decision_packet(
    frame, *, role="ImpactPlanner", max_chars=MAX_PLANNER_CONTEXT_CHARS,
    render=None, base_render=None, mandatory_core=None, legacy_render=None,
):
    """Compile the exact V24.4.3 choice projection packet.

    The full frame is validated first and is returned unchanged as the
    authoritative artifact.  Only the separate decision-relevant projection
    is rendered for the weak model.
    """
    frame_check = validate_impact_decision_frame(frame)
    if not frame_check.get("valid"):
        status = frame_check.get("status") or IMPACT_DECISION_FRAME_INCOMPLETE
        return {
            "status": status,
            "packet_complete": False,
            "errors": list(dict.fromkeys([status] + frame_check.get("errors", []))),
            "frame": copy.deepcopy(frame),
            "frame_validation": frame_check,
            "model_calls": 0,
        }
    projection = build_decision_relevant_impact_choice_projection(frame)
    projection_check = validate_decision_relevant_impact_choice_projection(
        projection, frame,
    )
    if not projection_check.get("valid"):
        status = IMPACT_DECISION_PROJECTION_INVALID
        return {
            "status": status,
            "packet_complete": False,
            "errors": list(dict.fromkeys([status] + projection_check.get("errors", []))),
            "frame": copy.deepcopy(frame),
            "frame_hash": frame.get("frame_hash"),
            "projection": copy.deepcopy(projection),
            "projection_validation": projection_check,
            "model_calls": 0,
        }
    payload = copy.deepcopy(projection.get("model_payload", {}))
    core = mandatory_core if isinstance(mandatory_core, dict) else {}
    coverage = core.get("mandatory_semantic_coverage", [])
    mandatory_ids = [
        "IMPACT_DECISION_FRAME", "IMPACT_DECISION_CONTRACT",
        "DECISION_RELEVANT_IMPACT_CHOICE_PROJECTION",
    ]
    mandatory_ids.extend(
        str(item) for item in projection.get("required_choice_slot_ids", []) or []
    )
    mandatory_ids.extend(
        str(item.get("canonical_semantic_id")) for item in coverage
        if isinstance(item, dict) and item.get("canonical_semantic_id")
    )
    mandatory_audit = audit_mandatory_planning_payload({**copy.deepcopy(payload), "packet_complete": True})
    legacy_payload = _impact_decision_frame_payload(frame)
    legacy_renderer = legacy_render if callable(legacy_render) else (
        render if callable(render) else base_render
    )
    legacy_rendered = None
    if callable(legacy_renderer):
        legacy_rendered = legacy_renderer(legacy_payload)
        if not isinstance(legacy_rendered, str):
            legacy_rendered = str(legacy_rendered)
    legacy_audit = audit_impact_decision_frame_model_payload(
        frame, legacy_payload, rendered=legacy_rendered,
    )
    role_packet = build_planning_role_packet(
        role, payload, [], hard_limit=max_chars, render=render, base_render=base_render,
        source_planning_context_hash=frame.get("source_planning_context_hash"),
        mandatory_items=mandatory_ids, planning_core_hash=frame.get("source_mandatory_core_hash"),
        mandatory_payload_audit=mandatory_audit,
        mandatory_semantic_coverage=coverage,
        mandatory_core_metrics=core.get("metrics") if isinstance(core, dict) else None,
    )
    role_packet["decision_relevant_impact_choice_projection"] = copy.deepcopy(projection)
    role_packet["legacy_payload_audit"] = copy.deepcopy(legacy_audit)
    role_packet["projection_validation"] = copy.deepcopy(projection_check)
    role_packet["projection_hash"] = projection.get("projection_hash")
    role_packet["full_frame_hash"] = frame.get("frame_hash")
    role_packet["required_choice_slot_ids"] = list(
        projection.get("required_choice_slot_ids", []) or []
    )
    role_packet["excluded_choice_slot_ids"] = list(
        projection.get("excluded_choice_slot_ids", []) or []
    )
    complete = bool(role_packet.get("packet_complete"))
    return {
        "version": 1,
        "artifact_type": "ImpactDecisionChoiceRequest",
        "packet": copy.deepcopy(role_packet.get("payload", payload)),
        "role_packet": copy.deepcopy(role_packet),
        "frame": copy.deepcopy(frame),
        "frame_hash": frame.get("frame_hash"),
        "projection": copy.deepcopy(projection),
        "projection_hash": projection.get("projection_hash"),
        "projection_validation": projection_check,
        "legacy_payload_audit": legacy_audit,
        "required_choice_slot_ids": list(projection.get("required_choice_slot_ids", []) or []),
        "excluded_choice_slot_ids": list(projection.get("excluded_choice_slot_ids", []) or []),
        "model_choice_semantic_coverage": projection.get("model_choice_semantic_coverage", 0.0),
        "full_authority_provenance_coverage": projection.get(
            "full_authority_provenance_coverage", 0.0,
        ),
        "required_model_choice_slots_total": projection.get(
            "required_model_choice_slots_total", 0,
        ),
        "required_model_choice_slots_rendered": projection.get(
            "required_model_choice_slots_rendered", 0,
        ),
        "required_model_choice_slot_coverage_rate": projection.get(
            "required_model_choice_slot_coverage_rate", 0.0,
        ),
        "full_frame_semantic_coverage": projection.get(
            "full_frame_semantic_coverage", 0.0,
        ),
        "full_provenance_reachable": projection.get(
            "full_provenance_reachable", 0.0,
        ),
        "projection_metrics": copy.deepcopy(projection.get("metrics", {})),
        "mandatory_semantic_coverage": copy.deepcopy(coverage),
        "mandatory_semantic_coverage_rate": role_packet.get("mandatory_semantic_coverage_rate", 1.0),
        "packet_chars": role_packet.get("rendered_chars", 0),
        "packet_complete": complete,
        "status": "READY" if complete else role_packet.get("status"),
        "errors": list(role_packet.get("errors", [])),
        "model_calls": 0,
    }


build_impact_decision_role_packet = build_impact_decision_packet


def _build_choice_coverage(frame, choices):
    """Compute selected-choice coverage from frame capability mappings."""
    value = frame if isinstance(frame, dict) else {}
    frame_coverage = _build_frame_coverage(value)
    if isinstance(choices, dict):
        selected = choices.get("decisions")
        if not isinstance(selected, list):
            selected = choices.get("choices", [])
    else:
        selected = choices if isinstance(choices, list) else []
    selected = list(selected or [])
    selected_by_slot = {
        str(item.get("slot_id")): item for item in selected
        if isinstance(item, dict) and item.get("slot_id")
    }
    slots = {
        str(item.get("slot_id")): item for item in list(value.get("decision_slots", []) or [])
        if isinstance(item, dict) and item.get("slot_id")
    }
    atomic_by_id = {
        str(item.get("obligation_id")): item
        for item in _atomic_obligation_records(value.get("requirement_obligation_ledger", {}))
        if item.get("obligation_id")
    }
    records = []
    assignments = []
    for obligation in list(frame_coverage.get("obligations", []) or []):
        obligation_id = str(obligation.get("obligation_id") or "")
        selected_slots = []
        selected_decisions = []
        covered_by = []
        for slot_id, choice in sorted(selected_by_slot.items()):
            slot = slots.get(slot_id, {})
            decision = str(choice.get("decision") or "").upper()
            if decision not in {
                str(item) for item in slot.get("allowed_decisions", []) or []
            }:
                continue
            obligation_source = atomic_by_id.get(obligation_id, obligation)
            surface = {
                "surface_id": slot.get("surface_id"),
                "kind": slot.get("surface_kind"),
                "role": slot.get("surface_role"),
                "path": slot.get("surface_path"),
                "symbol": slot.get("surface_symbol"),
                "structured_relations": list(
                    slot.get("surface_structured_relations", []) or []
                ),
            }
            # Recompute the contribution from canonical source obligation,
            # slot authority, and the existing decision taxonomy.  A copied
            # frame mapping is not a semantic shortcut for post-choice gate.
            if not _frame_decision_satisfies_obligation(
                obligation_source, slot, decision, surface,
            ):
                continue
            selected_slots.append(slot_id)
            selected_decisions.append(decision)
            capabilities = list(
                (slot.get("decision_capabilities", {}) or {}).get(decision)
                or _decision_capabilities(decision)
            )
            covered_by.append({
                "slot_id": slot_id,
                "surface_id": str(slot.get("surface_id") or ""),
                "decision": decision,
                "decision_capabilities": capabilities,
            })
        inherited_slots = list(obligation.get("inherited_slots", []) or [])
        inherited = bool(obligation.get("inherited_satisfaction"))
        inherited_assignment = None
        if inherited:
            for slot_id in inherited_slots:
                choice = selected_by_slot.get(str(slot_id))
                if not choice:
                    continue
                decision = str(choice.get("decision") or "").upper()
                inherited_assignment = {
                    "slot_id": str(slot_id),
                    "surface_id": str(slots.get(str(slot_id), {}).get("surface_id") or ""),
                    "decision": decision,
                    "decision_capabilities": _decision_capabilities(decision),
                }
                break
        obligation_type = str(obligation.get("obligation_type") or "").upper()
        if obligation_type == "BEHAVIOR_CHANGE":
            covered = any(
                "IMPLEMENTATION_CHANGE" in item.get("decision_capabilities", [])
                for item in covered_by
            )
        elif obligation_type == "PROHIBITION":
            covered = inherited
        else:
            covered = bool(covered_by) or inherited
        assignment = None
        if covered_by:
            assignment = covered_by[0]
            assignment = {
                **assignment,
                "coverage_contribution": assignment["decision_capabilities"][0]
                if assignment["decision_capabilities"] else "DECISION",
            }
        elif inherited_assignment and inherited:
            assignment = {
                **inherited_assignment,
                "coverage_contribution": (
                    "INHERITED_PRESERVATION"
                    if obligation_type == "PRESERVATION"
                    else "INHERITED_CONSTRAINT"
                ),
            }
        if assignment:
            assignments.append({
                "requirement_id": obligation.get("requirement_id"),
                "obligation_id": obligation_id,
                "obligation_type": obligation_type,
                "slot_id": assignment.get("slot_id"),
                "chosen_decision": assignment.get("decision"),
                "decision_capability": list(assignment.get("decision_capabilities", [])),
                "coverage_contribution": assignment.get("coverage_contribution"),
            })
        records.append({
            "obligation_id": obligation_id,
            "requirement_id": obligation.get("requirement_id"),
            "obligation_type": obligation_type,
            "meaning": obligation.get("meaning"),
            "candidate_slots": list(obligation.get("candidate_slots", []) or []),
            "candidate_decisions": list(obligation.get("candidate_decisions", []) or []),
            "selected_slots": list(dict.fromkeys(selected_slots)),
            "selected_decisions": list(dict.fromkeys(selected_decisions)),
            "inherited_satisfaction": inherited,
            "coverage_ready": bool(covered),
            "covered_by": covered_by,
            "assignment": copy.deepcopy(assignment),
        })
    uncovered = [
        item["obligation_id"] for item in records if not item.get("coverage_ready")
    ]
    artifact = {
        "version": 1,
        "artifact_type": "ImpactDecisionChoiceCoverage",
        "frame_coverage_hash": frame_coverage.get("coverage_hash"),
        "obligations": records,
        "assignments": assignments,
        "uncovered_obligations": uncovered,
        "uncovered_requirement_ids": list(dict.fromkeys(
            str(item.get("requirement_id")) for item in records
            if not item.get("coverage_ready")
        )),
        "coverage_status": IMPACT_CHOICE_COVERAGE_READY if not uncovered else IMPACT_CHOICE_REQUIREMENT_GAP,
        "metrics": {
            "impact_choice_covered_obligations": sum(
                bool(item.get("coverage_ready")) for item in records
            ),
            "impact_choice_uncovered_obligations": len(uncovered),
            "impact_requirements_assigned": len({
                str(item.get("requirement_id")) for item in assignments
                if item.get("requirement_id")
            }),
        },
    }
    artifact["choice_hash"] = impact_decision_choice_hash(
        frame, {"decisions": selected},
    )
    artifact["coverage_hash"] = _coverage_hash(artifact)
    return artifact


def build_impact_decision_choice_coverage(frame, choices):
    """Build the immutable zero-model post-choice coverage artifact."""
    return _build_choice_coverage(frame, choices)


def validate_impact_decision_choice_coverage(frame, choices):
    artifact = _build_choice_coverage(frame, choices)
    errors = []
    if artifact.get("uncovered_obligations"):
        errors.append(
            f"{IMPACT_CHOICE_REQUIREMENT_GAP}: "
            + ", ".join(artifact.get("uncovered_obligations", []))
        )
        if any(
            item.get("obligation_type") == "BEHAVIOR_CHANGE"
            for item in artifact.get("obligations", [])
            if not item.get("coverage_ready")
        ):
            errors.append(BEHAVIOR_CHANGE_UNCOVERED)
    return {
        "valid": not errors,
        "status": IMPACT_CHOICE_COVERAGE_READY if not errors else IMPACT_CHOICE_REQUIREMENT_GAP,
        "errors": errors,
        "coverage": artifact,
        "uncovered_obligations": list(artifact.get("uncovered_obligations", [])),
        "covered_obligations": artifact.get("metrics", {}).get("impact_choice_covered_obligations", 0),
        "obligations_total": len(artifact.get("obligations", [])),
        "model_calls": 0,
        "coverage_hash": artifact.get("coverage_hash"),
    }


def validate_impact_decision_choices(
    candidate, frame, *, include_coverage=True, projection=None,
    choice_projection=None,
):
    """Validate the strict choice-only response against the frame.

    ``include_coverage`` is false only for the provider's structural JSON
    callback.  Requirement coverage is a deterministic post-provider gate;
    keeping it out of the callback prevents a semantic coverage miss from
    entering the generic structured-output repair loop.
    """
    if projection is None:
        projection = choice_projection
    value = candidate if isinstance(candidate, dict) else {}
    errors = []
    if not isinstance(value.get("decisions"), list):
        return {
            "valid": False, "status": IMPACT_DECISION_OUTPUT_MALFORMED,
            "errors": [IMPACT_DECISION_OUTPUT_MALFORMED], "choices": [], "model_calls": 0,
            "structural_valid": False, "coverage_valid": None,
        }
    if set(value.keys()) != {"decisions"}:
        errors.append(IMPACT_DECISION_OUTPUT_MALFORMED + ": authority fields are not model-writable")
    frame_check = validate_impact_decision_frame(frame)
    if not frame_check.get("valid"):
        errors.append(IMPACT_DECISION_FRAME_INCOMPLETE)
    slots = {
        str(item.get("slot_id")): item for item in list(frame.get("decision_slots", []) or [])
        if isinstance(item, dict) and item.get("slot_id")
    }
    projection_check = None
    expected_slot_ids = set(slots)
    excluded_slot_ids = set()
    if projection is not None:
        projection_check = validate_decision_relevant_impact_choice_projection(
            projection, frame,
        )
        if not projection_check.get("valid"):
            errors.append(IMPACT_DECISION_PROJECTION_INVALID)
        expected_slot_ids = {
            str(item) for item in projection.get("required_choice_slot_ids", []) or []
        }
        excluded_slot_ids = set(slots).difference(expected_slot_ids)
    seen = set()
    choices = []
    for item in value.get("decisions", [])[:MAX_IMPACT_SEEDS + 1]:
        if not isinstance(item, dict):
            errors.append(IMPACT_DECISION_OUTPUT_MALFORMED)
            continue
        keys = set(item.keys())
        if keys != set(IMPACT_DECISION_MODEL_FIELDS):
            if keys.intersection(IMPACT_DECISION_AUTHORITY_FIELDS):
                errors.append(IMPACT_DECISION_OUTPUT_MALFORMED + ": authority field supplied by model")
            else:
                errors.append(IMPACT_DECISION_OUTPUT_MALFORMED)
            continue
        slot_id = str(item.get("slot_id") or "")
        if slot_id in seen:
            errors.append(DUPLICATE_IMPACT_DECISION_SLOT)
            continue
        seen.add(slot_id)
        slot = slots.get(slot_id)
        if slot is None:
            errors.append(UNKNOWN_IMPACT_DECISION_SLOT)
            continue
        if slot_id in excluded_slot_ids:
            errors.append(EXCLUDED_IMPACT_DECISION_SLOT)
            continue
        if any(not isinstance(item.get(field), str) or not item.get(field).strip()
               for field in ("decision", "chosen_target", "reason_code", "bounded_rationale")):
            errors.append(IMPACT_DECISION_OUTPUT_MALFORMED)
            continue
        decision = str(item.get("decision")).upper().strip()
        if decision not in set(str(value) for value in slot.get("allowed_decisions", []) or []):
            errors.append(IMPACT_DECISION_NOT_ALLOWED)
        target = str(item.get("chosen_target")).strip()
        if target not in set(str(value) for value in slot.get("allowed_targets", []) or []):
            errors.append(IMPACT_DECISION_TARGET_NOT_ALLOWED)
        if decision == "INTERFACE_REUSE" and target not in set(
            str(value) for value in slot.get("required_interfaces", []) or []
        ):
            errors.append(IMPACT_DECISION_TARGET_NOT_ALLOWED)
        if decision in {
            "MUST_CHANGE", "TEST_CHANGE", "PRESERVATION_ONLY", "VERIFY_ONLY", "INSPECT_ONLY",
        } and target != str(slot.get("surface_id")):
            errors.append(IMPACT_DECISION_TARGET_NOT_ALLOWED)
        if decision == "AUTHORITY_CHANGE" and target not in set(
            str(value) for value in slot.get("authority_change_targets", []) or []
        ):
            errors.append(IMPACT_DECISION_TARGET_NOT_ALLOWED)
        choices.append({
            "slot_id": slot_id, "decision": decision, "chosen_target": target,
            "reason_code": str(item.get("reason_code")).strip(),
            "bounded_rationale": _compact(item.get("bounded_rationale"), 360),
        })
    expected = set(expected_slot_ids)
    if seen.intersection(set(slots)).difference(expected):
        errors.append(EXCLUDED_IMPACT_DECISION_SLOT)
    if seen.difference(set(slots)):
        errors.append(UNKNOWN_IMPACT_DECISION_SLOT)
    missing = expected - seen
    if missing:
        errors.append(MISSING_IMPACT_DECISION_SLOT)
    if len(value.get("decisions", [])) > len(expected):
        # Unknown/duplicate is more informative when available; malformed
        # cardinality is retained for an array that only overflows.
        if not any(item in errors for item in (DUPLICATE_IMPACT_DECISION_SLOT, UNKNOWN_IMPACT_DECISION_SLOT)):
            errors.append(IMPACT_DECISION_OUTPUT_MALFORMED)
    errors = list(dict.fromkeys(errors))
    choices.sort(key=lambda item: str(item.get("slot_id") or ""))
    structural_valid = not errors and len(seen) == len(expected) and len(choices) == len(expected)
    choice_coverage = None
    if (
        include_coverage
        and structural_valid
    ):
        choice_coverage = validate_impact_decision_choice_coverage(frame, choices)
        if not choice_coverage.get("valid"):
            errors.extend(choice_coverage.get("errors", []))
    errors = list(dict.fromkeys(errors))
    valid = not errors and structural_valid
    return {
        "valid": valid,
        "status": "READY" if valid else (errors[0] if errors else IMPACT_DECISION_OUTPUT_MALFORMED),
        "errors": errors,
        "choices": choices if valid else [],
        "received": len(value.get("decisions", [])),
        "expected": len(expected),
        "model_calls": 0,
        "structural_valid": structural_valid,
        "projection_validation": copy.deepcopy(projection_check),
        "expected_slot_ids": sorted(expected),
        "excluded_slot_ids": sorted(excluded_slot_ids),
        "coverage_valid": (
            choice_coverage.get("valid") if isinstance(choice_coverage, dict) else None
        ),
        "choice_hash": impact_decision_choice_hash(frame, {"decisions": choices}) if valid else None,
        "choice_coverage": copy.deepcopy(
            choice_coverage.get("coverage") if isinstance(choice_coverage, dict) else None
        ),
        "coverage": copy.deepcopy(
            choice_coverage.get("coverage") if isinstance(choice_coverage, dict) else None
        ),
        "uncovered_obligations": list(
            choice_coverage.get("uncovered_obligations", [])
            if isinstance(choice_coverage, dict) else []
        ),
        "coverage_status": (
            choice_coverage.get("status") if isinstance(choice_coverage, dict) else None
        ),
        "coverage_hash": (
            choice_coverage.get("coverage_hash")
            if isinstance(choice_coverage, dict) else None
        ),
    }


validate_impact_decision_output = validate_impact_decision_choices


def deterministic_impact_decision_choices(frame, projection=None, *, required_only=None):
    """Produce a provider-free weak-choice fixture for architecture tests."""
    if required_only is None:
        required_only = projection is not None
    required_ids = {
        str(item) for item in list(
            (projection or {}).get("required_choice_slot_ids", []) or []
        )
    } if isinstance(projection, dict) else set()
    result = []
    for slot in list((frame or {}).get("decision_slots", []) or []):
        if required_only and str(slot.get("slot_id") or "") not in required_ids:
            continue
        allowed = [str(item) for item in slot.get("allowed_decisions", []) or []]
        if not allowed:
            continue
        # This helper is a provider-free architecture fixture, not a model
        # repair path.  Keep its default output planning-complete when the
        # frame explicitly proves that MUST_CHANGE is the only capability
        # that can satisfy an active behavior obligation.
        behavior_ids = set(
            str(item) for item in (slot.get("obligations_satisfied_by_decision", {}) or {}).get(
                "MUST_CHANGE", []
            )
        )
        if "MUST_CHANGE" in allowed and behavior_ids:
            decision = "MUST_CHANGE"
            target = str(slot.get("surface_id"))
            reason_code = "CHANGE_REQUIRED"
            rationale = "Apply the requirement through the verified current surface."
        elif "INTERFACE_REUSE" in allowed and slot.get("required_interfaces"):
            decision = "INTERFACE_REUSE"
            target = str(slot.get("required_interfaces")[0])
            reason_code = "REUSE_CURRENT_INTERFACE"
            rationale = "Reuse the verified current interface for this bounded slot."
        elif "TEST_CHANGE" in allowed:
            decision = "TEST_CHANGE"
            target = str(slot.get("surface_id"))
            reason_code = "TEST_BOUNDARY"
            rationale = "Keep the decision at the verified test boundary."
        elif "PRESERVATION_ONLY" in allowed:
            decision = "PRESERVATION_ONLY"
            target = str(slot.get("surface_id"))
            reason_code = "PRESERVE_CURRENT_BEHAVIOR"
            rationale = "Preserve the verified current behavior without mutation."
        elif "VERIFY_ONLY" in allowed:
            decision = "VERIFY_ONLY"
            target = str(slot.get("surface_id"))
            reason_code = "INSPECT_CURRENT_SURFACE"
            rationale = "Inspect the verified current surface without mutation."
        elif "INSPECT_ONLY" in allowed:
            decision = "INSPECT_ONLY"
            target = str(slot.get("surface_id"))
            reason_code = "INSPECT_CURRENT_SURFACE"
            rationale = "Inspect the verified current surface without mutation."
        elif "MUST_CHANGE" in allowed:
            # A MUST_CHANGE fallback is used only when the frame did not
            # expose a safer bounded choice.  In obligation-aware mode a
            # behavior obligation reaches this branch only after the
            # capability-bearing MUST_CHANGE decision was explicitly linked
            # above; an unbound surface should never be mutated by default.
            decision = "MUST_CHANGE"
            target = str(slot.get("surface_id"))
            reason_code = "CHANGE_REQUIRED"
            rationale = "Apply the requirement through the verified current surface."
        else:
            decision = allowed[0]
            target = str(slot.get("surface_id"))
            reason_code = "INSPECT_CURRENT_SURFACE"
            rationale = "Keep the choice bounded to the verified surface."
        result.append({
            "slot_id": slot.get("slot_id"), "decision": decision, "chosen_target": target,
            "reason_code": reason_code, "bounded_rationale": rationale,
        })
    return {"decisions": result}


def _deterministic_nonrequired_choice(slot, classification):
    """Materialize a safe non-model choice from an audited slot.

    These choices are compiler inputs only.  They are never exposed in the
    model response contract and they never create mutation authority.
    """
    value = slot if isinstance(slot, dict) else {}
    allowed = [str(item) for item in list(value.get("allowed_decisions", []) or [])]
    surface_id = str(value.get("surface_id") or "")
    if "PRESERVATION_ONLY" in allowed and classification == "DETERMINISTIC_INHERITED_ONLY":
        return {
            "slot_id": str(value.get("slot_id")), "decision": "PRESERVATION_ONLY",
            "chosen_target": surface_id, "reason_code": "PRESERVE_INHERITED_STATE",
            "bounded_rationale": "Preserve the inherited verified state without mutation.",
        }
    if "INTERFACE_REUSE" in allowed and value.get("required_interfaces"):
        return {
            "slot_id": str(value.get("slot_id")), "decision": "INTERFACE_REUSE",
            "chosen_target": str(value.get("required_interfaces")[0]),
            "reason_code": "REUSE_INHERITED_INTERFACE",
            "bounded_rationale": "Reuse the inherited verified interface without changing ownership.",
        }
    for decision, reason, rationale in (
        ("VERIFY_ONLY", "VERIFY_INHERITED_STATE", "Verify the inherited verified state without mutation."),
        ("INSPECT_ONLY", "INSPECT_INHERITED_STATE", "Inspect the verified context without mutation."),
    ):
        if decision in allowed:
            return {
                "slot_id": str(value.get("slot_id")), "decision": decision,
                "chosen_target": surface_id, "reason_code": reason,
                "bounded_rationale": rationale,
            }
    return None


def _compiled_preservation_texts(slot):
    return _bounded_strings([
        item.get("text") if isinstance(item, dict) else item
        for item in list(slot.get("required_preservation_promises", []) or [])
    ], 8, 300)


def _compiled_verification_texts(slot):
    return _bounded_strings([
        item.get("text") if isinstance(item, dict) else item
        for item in list(slot.get("required_verification_contracts", []) or [])
    ], 8, 300)


def compile_impact_map_from_choices(
    frame, choices, requirements, evidence, surface_registry=None,
    impact_seeds=None, *, task_goal=None, provider_generation_identity=None,
    projection=None, choice_projection=None,
):
    """Compile validated choices into the existing canonical Impact Map.

    This function is deliberately fail-closed.  It never calls a provider and
    it never hydrates an invalid or legacy response into a valid map.
    """
    frame_check = validate_impact_decision_frame(frame)
    if not frame_check.get("valid"):
        status = frame_check.get("status") or IMPACT_MAP_COMPILE_INVALID
        return {
            "valid": False, "status": status,
            "errors": list(dict.fromkeys([status] + frame_check.get("errors", []))),
            "impact_map": None, "model_calls": 0, "compiled": False,
        }
    if projection is None:
        projection = choice_projection
    choice_candidate = choices
    if isinstance(choices, dict) and "decisions" not in choices and isinstance(
        choices.get("choices"), list
    ):
        # Accept the deterministic validator artifact produced by the normal
        # orchestration path, while still re-running the strict contract gate
        # before compilation.
        choice_candidate = {"decisions": choices.get("choices", [])}
    choice_check = validate_impact_decision_choices(
        choice_candidate, frame, projection=projection,
    )
    if not choice_check.get("valid"):
        status = choice_check.get("status") or IMPACT_MAP_COMPILE_INVALID
        return {
            "valid": False, "status": status,
            "errors": list(choice_check.get("errors", [])) or [status],
            "impact_map": None, "model_calls": 0, "compiled": False,
        }
    registry = surface_registry if isinstance(surface_registry, dict) else {}
    reqs = active_requirements(requirements or [])
    by_surface = canonical_surface_by_id(registry)
    seeds = [item for item in list(impact_seeds or []) if isinstance(item, dict)]
    seed_by_id = {str(item.get("seed_id")): item for item in seeds if item.get("seed_id")}
    slots = {
        str(item.get("slot_id")): item for item in list(frame.get("decision_slots", []) or [])
        if isinstance(item, dict)
    }
    provided_choices = [
        copy.deepcopy(item) for item in list(choice_check.get("choices", []) or [])
        if isinstance(item, dict)
    ]
    effective_choices = list(provided_choices)
    if projection is not None:
        classifications = {
            str(item.get("slot_id")): item
            for item in list(projection.get("slot_classification", []) or [])
            if isinstance(item, dict) and item.get("slot_id")
        }
        provided_ids = {str(item.get("slot_id")) for item in effective_choices}
        for slot_id, slot in slots.items():
            if slot_id in provided_ids:
                continue
            classification = classifications.get(slot_id, {}).get("classification")
            if classification == "MODEL_CHOICE_REQUIRED":
                continue
            materialized = _deterministic_nonrequired_choice(slot, classification)
            if materialized is None:
                return {
                    "valid": False,
                    "status": IMPACT_DECISION_PROJECTION_INVALID,
                    "errors": [
                        f"{IMPACT_DECISION_PROJECTION_INVALID}: no safe deterministic choice for {slot_id}"
                    ],
                    "impact_map": None, "model_calls": 0, "compiled": False,
                }
            effective_choices.append(materialized)
        effective_choices.sort(key=lambda item: str(item.get("slot_id") or ""))
    disposition_for_choice = {
        "INSPECT_ONLY": "VERIFY_ONLY", "AUTHORITY_CHANGE": "MUST_CHANGE",
    }
    raw_impacts = []
    authority_changes_by_impact = {}
    inherited_by_impact = {}
    choice_hash = choice_check.get("choice_hash") or impact_decision_choice_hash(frame, choices)
    choice_coverage = _build_choice_coverage(frame, effective_choices)
    choice_assignments = list(choice_coverage.get("assignments", []) or [])
    assignments_by_slot = {}
    for assignment in choice_assignments:
        if isinstance(assignment, dict) and assignment.get("slot_id"):
            assignments_by_slot.setdefault(str(assignment.get("slot_id")), []).append(assignment)
    atomic_by_id = {
        str(item.get("obligation_id")): item
        for item in _atomic_obligation_records(frame.get("requirement_obligation_ledger", {}))
        if item.get("obligation_id")
    }
    compiled_assignments_by_impact = {}
    errors = []
    for choice in effective_choices:
        slot = slots.get(str(choice.get("slot_id")))
        if not slot:
            errors.append(UNKNOWN_IMPACT_DECISION_SLOT)
            continue
        surface = by_surface.get(str(slot.get("surface_id")))
        seed = seed_by_id.get(str(slot.get("seed_id")))
        if not surface or not seed:
            errors.append(f"{slot.get('slot_id')}: deterministic surface/seed binding is missing")
            continue
        decision = str(choice.get("decision") or "").upper()
        disposition = disposition_for_choice.get(decision, decision)
        if disposition not in DISPOSITIONS:
            errors.append(f"{slot.get('slot_id')}: unsupported compiled disposition")
            continue
        rationale = _compact(choice.get("bounded_rationale"), MAX_TEXT_CHARS)
        reason_code = _compact(choice.get("reason_code"), 120)
        if not rationale or not reason_code:
            errors.append(IMPACT_DECISION_OUTPUT_MALFORMED)
            continue
        selected_capabilities = list(
            (slot.get("decision_capabilities", {}) or {}).get(decision)
            or _decision_capabilities(decision)
        )
        slot_assignments = []
        for assignment in assignments_by_slot.get(str(slot.get("slot_id")), []):
            obligation_id = str(assignment.get("obligation_id") or "")
            obligation = atomic_by_id.get(obligation_id, {})
            slot_assignments.append({
                "requirement_id": assignment.get("requirement_id") or obligation.get("requirement_id"),
                "obligation_id": obligation_id,
                "obligation_type": assignment.get("obligation_type") or obligation.get("obligation_type"),
                "surface_id": str(slot.get("surface_id")),
                "slot_id": str(slot.get("slot_id")),
                "chosen_decision": assignment.get("chosen_decision") or decision,
                "decision_capability": list(
                    assignment.get("decision_capability") or selected_capabilities
                ),
                "coverage_contribution": assignment.get("coverage_contribution") or (
                    selected_capabilities[0] if selected_capabilities else "DECISION"
                ),
                "frame_provenance": {
                    "impact_decision_frame_hash": frame.get("frame_hash"),
                    "slot_id": str(slot.get("slot_id")),
                    "surface_id": str(slot.get("surface_id")),
                    "source_planning_context_hash": frame.get("source_planning_context_hash"),
                    "source_mandatory_core_hash": frame.get("source_mandatory_core_hash"),
                },
                "choice_provenance": {
                    "impact_decision_choice_hash": choice_hash,
                    "slot_id": str(slot.get("slot_id")),
                },
            })
        compiled_assignments_by_impact[normalize_impact_id(seed.get("impact_id"))] = slot_assignments
        interface_ids = []
        interface_names = []
        target = str(choice.get("chosen_target") or "")
        if decision == "INTERFACE_REUSE":
            candidates = [
                item for item in list(slot.get("interface_provenance", []) or [])
                if str(item.get("surface_id")) == target
            ]
            if candidates:
                interface_ids = [target]
                interface_names = [str(candidates[0].get("symbol") or "")]
            elif target in set(str(item) for item in slot.get("required_interfaces", []) or []):
                interface_ids = [target]
                interface = by_surface.get(target)
                interface_names = [str((interface or {}).get("symbol") or "")]
        req_ids = [
            str(item) for item in list(slot.get("requirement_ids", []) or [])
            if str(item) in {req["requirement_id"] for req in reqs}
        ]
        evidence_refs = _bounded_ids(surface.get("evidence_ids"), MAX_EVIDENCE_REFS_PER_IMPACT)
        raw_impacts.append({
            "impact_id": normalize_impact_id(seed.get("impact_id")),
            "surface_id": str(slot.get("surface_id")),
            "seed_id": str(slot.get("seed_id")),
            "disposition": disposition,
            "requirement_ids": req_ids,
            "obligation_ids": [
                str(item.get("obligation_id")) for item in slot_assignments
                if item.get("obligation_id")
            ],
            "obligation_assignments": copy.deepcopy(slot_assignments),
            "decision_slot_id": str(slot.get("slot_id")),
            "chosen_decision": decision,
            "decision_capabilities": selected_capabilities,
            "coverage_contribution": list(dict.fromkeys(
                str(item.get("coverage_contribution")) for item in slot_assignments
                if item.get("coverage_contribution")
            )),
            "frame_provenance": {
                "impact_decision_frame_hash": frame.get("frame_hash"),
                "slot_id": str(slot.get("slot_id")),
                "surface_id": str(slot.get("surface_id")),
            },
            "choice_provenance": {
                "impact_decision_choice_hash": choice_hash,
                "slot_id": str(slot.get("slot_id")),
            },
            "repository_evidence_ids": evidence_refs,
            "interfaces_to_reuse": interface_ids,
            "existing_interfaces_to_reuse": interface_names,
            "action": rationale,
            "candidate_change": rationale,
            "reason": f"{reason_code}: {rationale}",
            "preserve": _compiled_preservation_texts(slot),
            "local_preservation_constraints": _compiled_preservation_texts(slot),
            "prohibition_constraints": _bounded_strings(slot.get("prohibitions"), 8, 320),
            "verification": _compiled_verification_texts(slot),
            "local_verification": _compiled_verification_texts(slot),
            "test_contract": _compiled_verification_texts(slot),
            "local_test_contract": _compiled_verification_texts(slot),
            "necessity_status": {
                "MUST_CHANGE": "MUST_CHANGE", "PRESERVATION_ONLY": "PRESERVATION_ONLY",
                "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE",
            }.get(disposition, "CANDIDATE"),
        })
        if decision == "AUTHORITY_CHANGE":
            authority_changes_by_impact[normalize_impact_id(seed.get("impact_id"))] = {
                "type": "AUTHORITY_CHANGE",
                "from": (slot.get("current_owner") or {}).get("symbol")
                if isinstance(slot.get("current_owner"), dict) else None,
                "to": target,
                "authorized": True,
                "provenance": "EXPLICIT_REQUIREMENT_AUTHORITY",
            }
        inherited_by_impact[normalize_impact_id(seed.get("impact_id"))] = {
            "seed_id": str(slot.get("seed_id")),
            "surface_id": str(slot.get("surface_id")),
            "current_owner": copy.deepcopy(slot.get("current_owner")),
            "required_interfaces": copy.deepcopy(slot.get("required_interfaces", [])),
            "required_preservation_promises": copy.deepcopy(slot.get("required_preservation_promises", [])),
            "required_verification_contracts": copy.deepcopy(slot.get("required_verification_contracts", [])),
            "dnt": copy.deepcopy(slot.get("dnt", [])),
            "prohibitions": copy.deepcopy(slot.get("prohibitions", [])),
        }
    compiled_obligation_assignments = [
        assignment
        for slot in slots.values()
        for assignment in compiled_assignments_by_impact.get(
            normalize_impact_id(slot.get("impact_id")), []
        )
    ]
    behavior_requirement_ids = {
        str(item.get("requirement_id")) for item in atomic_by_id.values()
        if item.get("obligation_type") == "BEHAVIOR_CHANGE"
    }
    assigned_requirement_ids = {
        str(item.get("requirement_id")) for item in choice_assignments
        if item.get("requirement_id")
    }
    missing_assigned_requirements = sorted(behavior_requirement_ids - assigned_requirement_ids)
    if missing_assigned_requirements:
        errors.append(
            f"{IMPACT_CHOICE_REQUIREMENT_GAP}: active changed requirements have no assigned impact: "
            + ", ".join(missing_assigned_requirements)
        )
    if errors or len(raw_impacts) != len(slots):
        status = (
            IMPACT_CHOICE_REQUIREMENT_GAP
            if any(str(item).startswith(IMPACT_CHOICE_REQUIREMENT_GAP) for item in errors)
            else IMPACT_MAP_COMPILE_INVALID
        )
        return {
            "valid": False, "status": status,
            "errors": list(dict.fromkeys(errors + ([status] if not errors else []))),
            "impact_map": None, "model_calls": 0, "compiled": False,
        }
    raw_map = {
        "version": 1,
        "task_goal": task_goal or "",
        "impacts": raw_impacts,
        "integration_verification": [],
        "insufficient_evidence": [],
        "new_surface_proposals": [],
        "requirement_obligation_ledger": compact_requirement_obligation_ledger(
            frame.get("requirement_obligation_ledger", {})
        ),
        "impact_decision_frame_coverage": copy.deepcopy(
            frame.get("impact_decision_frame_coverage", {})
        ),
        "impact_decision_choice_coverage": copy.deepcopy(choice_coverage),
        "obligation_assignments": copy.deepcopy(compiled_obligation_assignments),
        "bounds": {
            "max_impact_entries": MAX_IMPACT_ENTRIES,
            "max_requirement_refs_per_impact": MAX_REQUIREMENT_REFS_PER_IMPACT,
            "max_evidence_refs_per_impact": MAX_EVIDENCE_REFS_PER_IMPACT,
        },
        "provenance": DERIVED_PLAN_DECISION,
    }
    hydrated = hydrate_impact_map(
        raw_map, registry, reqs, evidence,
        allow_legacy_exact=False, impact_seeds=seeds,
    )
    if not hydrated.get("hydration_valid") or not hydrated.get("impacts"):
        return {
            "valid": False, "status": IMPACT_MAP_COMPILE_INVALID,
            "errors": list(hydrated.get("hydration_errors", [])) or [IMPACT_MAP_COMPILE_INVALID],
            "impact_map": None, "hydration": hydrated, "model_calls": 0, "compiled": False,
        }
    for item in hydrated.get("impacts", []):
        impact_id = normalize_impact_id(item.get("impact_id"))
        inherited = inherited_by_impact.get(impact_id, {})
        item["seed_id"] = inherited.get("seed_id")
        item["current_owner"] = copy.deepcopy(inherited.get("current_owner"))
        item["required_interfaces"] = copy.deepcopy(inherited.get("required_interfaces", []))
        item["preservation_promises"] = copy.deepcopy(inherited.get("required_preservation_promises", []))
        item["required_preservation_promises"] = copy.deepcopy(inherited.get("required_preservation_promises", []))
        item["verification_contracts"] = copy.deepcopy(inherited.get("required_verification_contracts", []))
        item["required_verification_contracts"] = copy.deepcopy(inherited.get("required_verification_contracts", []))
        item["dnt"] = copy.deepcopy(inherited.get("dnt", []))
        item["prohibitions"] = copy.deepcopy(inherited.get("prohibitions", []))
        item_assignments = copy.deepcopy(compiled_assignments_by_impact.get(impact_id, []))
        item["obligation_ids"] = [
            str(value.get("obligation_id")) for value in item_assignments
            if value.get("obligation_id")
        ]
        item["obligation_assignments"] = item_assignments
        item["decision_slot_id"] = next(
            (
                str(value.get("slot_id")) for value in item_assignments
                if value.get("slot_id")
            ),
            next((str(slot.get("slot_id")) for slot in slots.values()
                  if normalize_impact_id(slot.get("impact_id")) == impact_id), None),
        )
        choice_for_item = next(
            (value for value in effective_choices
             if str(value.get("slot_id")) == str(item.get("decision_slot_id"))),
            None,
        )
        if choice_for_item:
            item["chosen_decision"] = choice_for_item.get("decision")
            item["decision_capabilities"] = _decision_capabilities(
                choice_for_item.get("decision")
            )
        item["coverage_contribution"] = list(dict.fromkeys(
            str(value.get("coverage_contribution")) for value in item_assignments
            if value.get("coverage_contribution")
        ))
        item["frame_provenance"] = {
            "impact_decision_frame_hash": frame.get("frame_hash"),
            "slot_id": item.get("decision_slot_id"),
            "surface_id": item.get("surface_id"),
        }
        item["choice_provenance"] = {
            "impact_decision_choice_hash": choice_hash,
            "slot_id": item.get("decision_slot_id"),
        }
        if impact_id in authority_changes_by_impact:
            item["authority_change"] = copy.deepcopy(authority_changes_by_impact[impact_id])
        item["impact_decision_frame_hash"] = frame.get("frame_hash")
        item["impact_decision_choice_hash"] = choice_hash
        item["source_planning_context_hash"] = frame.get("source_planning_context_hash")
        item["source_mandatory_core_hash"] = frame.get("source_mandatory_core_hash")
        item["provider_generation_identity"] = copy.deepcopy(
            provider_generation_identity if provider_generation_identity is not None else "UNSPECIFIED"
        )
    hydrated["task_goal"] = _compact(task_goal or hydrated.get("task_goal"), 1000)
    hydrated["impact_decision_frame_hash"] = frame.get("frame_hash")
    hydrated["impact_decision_choice_hash"] = choice_hash
    hydrated["source_planning_context_hash"] = frame.get("source_planning_context_hash")
    hydrated["source_mandatory_core_hash"] = frame.get("source_mandatory_core_hash")
    hydrated["requirement_obligation_ledger"] = compact_requirement_obligation_ledger(
        frame.get("requirement_obligation_ledger", {})
    )
    hydrated["impact_decision_frame_coverage"] = copy.deepcopy(
        frame.get("impact_decision_frame_coverage", {})
    )
    hydrated["impact_decision_choice_coverage"] = copy.deepcopy(choice_coverage)
    hydrated["obligation_assignments"] = copy.deepcopy(compiled_obligation_assignments)
    hydrated["obligation_assignment_requirement_ids"] = sorted({
        str(item.get("requirement_id")) for item in choice_assignments
        if item.get("requirement_id")
    })
    hydrated["provider_generation_identity"] = copy.deepcopy(
        provider_generation_identity if provider_generation_identity is not None else "UNSPECIFIED"
    )
    hydrated["planning_provenance"] = {
        "source_planning_context_hash": frame.get("source_planning_context_hash"),
        "source_mandatory_core_hash": frame.get("source_mandatory_core_hash"),
        "impact_decision_frame_hash": frame.get("frame_hash"),
        "impact_decision_choice_hash": choice_hash,
        "provider_generation_identity": copy.deepcopy(
            provider_generation_identity if provider_generation_identity is not None else "UNSPECIFIED"
        ),
    }
    semantic_validation = validate_impact_map(
        hydrated, reqs, evidence, EXISTING_PROJECT, surface_registry=registry,
    )
    if not semantic_validation.get("valid"):
        return {
            "valid": False, "status": IMPACT_MAP_COMPILE_INVALID,
            "errors": semantic_validation.get("errors", []) or [IMPACT_MAP_COMPILE_INVALID],
            "impact_map": None, "hydration": hydrated,
            "semantic_validation": semantic_validation, "model_calls": 0, "compiled": False,
        }
    return {
        "valid": True, "status": "READY", "errors": [],
        "impact_map": hydrated, "hydration": hydrated,
        "semantic_validation": semantic_validation,
        "choice_validation": choice_check,
        "effective_choices": {"decisions": copy.deepcopy(effective_choices)},
        "choice_hash": choice_hash,
        "choice_coverage": copy.deepcopy(choice_coverage),
        "coverage_hash": choice_coverage.get("coverage_hash") if isinstance(choice_coverage, dict) else None,
        "assigned_requirement_ids": sorted(assigned_requirement_ids),
        "model_calls": 0, "compiled": True,
        "inherited_preservation_count": sum(
            len(item.get("preservation_promises", []) or []) for item in hydrated.get("impacts", [])
        ),
        "inherited_verification_count": sum(
            len(item.get("verification_contracts", []) or []) for item in hydrated.get("impacts", [])
        ),
    }


compile_impact_map_from_decisions = compile_impact_map_from_choices
compile_impact_decision_map = compile_impact_map_from_choices


def impact_decision_frame_self_test():
    """Provider-free V24.4 architecture self-test and diagnostics."""
    requirement = {
        "requirement_id": "REQ-SELF-PAUSE",
        "text": (
            "Add a pause indicator while preserving PauseController as the sole pause-state owner, "
            "Escape behavior, and movement behavior."
        ),
        "provenance": USER_STATED,
    }
    evidence = [
        {
            "evidence_id": "REPO-SELF-OWNER", "category": "CURRENT_STATE_OWNER",
            "path": "src/pause_controller.js", "symbol": "PauseController",
            "fact": "PauseController owns pause state", "file_sha256": "a" * 64,
        },
        {
            "evidence_id": "REPO-SELF-INTERFACE", "category": "CURRENT_INTERFACE",
            "path": "src/pause_controller.js", "symbol": "PauseController.togglePause",
            "fact": "PauseController.togglePause is the current pause transition interface",
            "file_sha256": "b" * 64,
        },
        {
            "evidence_id": "REPO-SELF-TEST", "category": "CURRENT_TEST",
            "path": "tests/pause.test.js", "symbol": "pause flow",
            "fact": "focused tests cover Escape and movement behavior", "file_sha256": "c" * 64,
        },
    ]
    brain = {
        "project_id": "self-test-project", "task_id": "self-test-task",
        "task_goal": {"text": requirement["text"]},
        "current_owners": [{
            "text": "PauseController owns pause state", "path": "src/pause_controller.js",
            "symbol": "PauseController", "category": "CURRENT_STATE_OWNER",
            "evidence_ids": ["REPO-SELF-OWNER"],
        }],
        "current_state_ownership": [{
            "text": "PauseController owns pause state", "path": "src/pause_controller.js",
            "symbol": "PauseController", "category": "CURRENT_STATE_OWNER",
            "evidence_ids": ["REPO-SELF-OWNER"],
        }],
        "current_interfaces": [{
            "text": "PauseController.togglePause is current", "path": "src/pause_controller.js",
            "symbol": "PauseController.togglePause", "category": "CURRENT_INTERFACE",
            "evidence_ids": ["REPO-SELF-INTERFACE"],
        }],
        "relevant_tests": [{
            "text": "focused tests cover Escape and movement behavior", "path": "tests/pause.test.js",
            "symbol": "pause flow", "category": "CURRENT_TEST",
            "evidence_ids": ["REPO-SELF-TEST"],
        }],
        "preservation_constraints": [{"text": requirement["text"], "provenance": USER_STATED}],
        "dnt": ["Do not create a second pause-state owner."],
        "prohibitions": ["Do not create a second pause-state owner."],
    }
    requirements = [requirement]
    registry = build_canonical_surface_registry(brain, evidence)
    seeds = build_impact_seeds(brain, requirements, evidence, registry=registry)
    core = build_canonical_mandatory_planning_core({
        "project_id": brain["project_id"], "task_id": brain["task_id"],
        "task_goal": brain["task_goal"], "requirements": requirements,
        "surfaces": registry.get("surfaces", []), "impact_seeds": seeds,
        "preservation_constraints": brain["preservation_constraints"],
        "dnt": brain["dnt"], "prohibitions": brain["prohibitions"],
    })
    frame = build_impact_decision_frame(
        brain, requirements, evidence, surface_registry=registry,
        impact_seeds=seeds, mandatory_core=core,
    )
    frame_check = validate_impact_decision_frame(frame)
    projection = build_decision_relevant_impact_choice_projection(frame)
    projection_check = validate_decision_relevant_impact_choice_projection(
        projection, frame,
    )
    choices = deterministic_impact_decision_choices(frame, projection=projection)
    choice_check = validate_impact_decision_choices(
        choices, frame, projection=projection,
    )
    compiled = compile_impact_map_from_choices(
        frame, choices, requirements, evidence, surface_registry=registry,
        impact_seeds=seeds, task_goal=requirement["text"],
        provider_generation_identity={"model": "gemma4:e4b", "generation": 0},
        projection=projection,
    )
    legacy = {
        "impacts": [{
            "impact_id": "IMPACT-001", "disposition": "INTERFACE_REUSE",
            "requirement_ids": [requirement["requirement_id"]],
            "preservation_promises": [], "verification_contracts": [],
            "action": "Reuse IFACE-1",
        }],
    }
    legacy_check = validate_impact_decision_choices(legacy, frame)
    duplicate = copy.deepcopy(choices)
    if duplicate.get("decisions"):
        duplicate["decisions"] = [duplicate["decisions"][0], duplicate["decisions"][0]]
    duplicate_check = validate_impact_decision_choices(
        duplicate, frame, projection=projection,
    )
    missing = copy.deepcopy(choices)
    if missing.get("decisions"):
        missing["decisions"] = missing["decisions"][:-1]
    missing_check = validate_impact_decision_choices(
        missing, frame, projection=projection,
    )
    forbidden = copy.deepcopy(choices)
    if forbidden.get("decisions"):
        forbidden["decisions"][0]["decision"] = "NEW_OWNER"
    forbidden_check = validate_impact_decision_choices(
        forbidden, frame, projection=projection,
    )
    packet = build_impact_decision_packet(
        frame, render=lambda value: "IMPACT DECISION PACKET:\n" + _compact_json(value),
        base_render=lambda value: "IMPACT DECISION PACKET:\n" + _compact_json(value),
        mandatory_core=core,
    )
    checks = {
        "frame_complete": frame_check.get("valid") is True,
        "frame_zero_model": frame_check.get("model_calls") == 0,
        "projection_valid": projection_check.get("valid") is True,
        "projection_zero_model": projection_check.get("model_calls") == 0,
        "projection_preserves_frame_hash": (
            frame.get("frame_hash") == impact_decision_frame_hash(frame)
        ),
        "projection_required_choice_is_bounded": (
            set(projection.get("required_choice_slot_ids", [])).issubset(
                {str(item.get("slot_id")) for item in frame.get("decision_slots", [])}
            )
        ),
        "choices_valid": choice_check.get("valid") is True,
        "compiled_valid": compiled.get("valid") is True,
        "compiled_zero_model": compiled.get("model_calls") == 0,
        "compiled_semantic_validation": compiled.get("semantic_validation", {}).get("valid") is True,
        "inherited_preservation": bool(compiled.get("inherited_preservation_count")),
        "inherited_verification": bool(compiled.get("inherited_verification_count")),
        "legacy_failed_output_rejected": (
            legacy_check.get("valid") is False
            and legacy_check.get("status") == IMPACT_DECISION_OUTPUT_MALFORMED
        ),
        "duplicate_rejected": DUPLICATE_IMPACT_DECISION_SLOT in duplicate_check.get("errors", []),
        "missing_rejected": MISSING_IMPACT_DECISION_SLOT in missing_check.get("errors", []),
        "forbidden_rejected": IMPACT_DECISION_NOT_ALLOWED in forbidden_check.get("errors", []),
        "packet_fits": packet.get("packet_complete") is True and packet.get("packet_chars", 0) <= MAX_PLANNER_CONTEXT_CHARS,
        "packet_exact_render": (
            packet.get("role_packet", {}).get("exact_model_input")
            == packet.get("role_packet", {}).get("rendered_packet")
        ),
    }
    # Scientific regression cases: each is deterministic and provider-free.
    # Case A intentionally has only TEST evidence, so the frame cannot expose
    # an implementation-capable decision for the active behavior obligation.
    bad_frame_requirement = {
        "requirement_id": "REQ-SELF-LIVE-BAD",
        "text": "Add a user-facing pause indicator.",
        "provenance": USER_STATED,
        "status": "active",
    }
    bad_frame_evidence = [{
        "evidence_id": "REPO-SELF-LIVE-TEST-1",
        "category": "CURRENT_TEST",
        "path": "tests/pause.test.js",
        "symbol": "pause flow",
        "fact": "focused pause tests cover the current boundary",
        "file_sha256": "d" * 64,
    }, {
        "evidence_id": "REPO-SELF-LIVE-TEST-2",
        "category": "CURRENT_TEST",
        "path": "tests/pause-extra.test.js",
        "symbol": "pause indicator flow",
        "fact": "focused pause indicator tests cover the current boundary",
        "file_sha256": "e" * 64,
    }]
    bad_frame_brain = {
        "project_id": "self-test-project",
        "task_id": "self-test-live-bad",
        "task_goal": {"text": bad_frame_requirement["text"]},
        "relevant_tests": [{
            "text": "focused pause tests cover the current boundary",
            "path": "tests/pause.test.js", "symbol": "pause flow",
            "category": "CURRENT_TEST",
            "evidence_ids": ["REPO-SELF-LIVE-TEST-1"],
        }],
    }
    bad_registry = build_canonical_surface_registry(bad_frame_brain, bad_frame_evidence)
    bad_seeds = build_impact_seeds(
        bad_frame_brain, [bad_frame_requirement], bad_frame_evidence,
        registry=bad_registry,
    )
    bad_core = build_canonical_mandatory_planning_core({
        "project_id": bad_frame_brain["project_id"],
        "task_id": bad_frame_brain["task_id"],
        "task_goal": bad_frame_brain["task_goal"],
        "requirements": [bad_frame_requirement],
        "surfaces": bad_registry.get("surfaces", []),
        "impact_seeds": bad_seeds,
    })
    bad_frame = build_impact_decision_frame(
        bad_frame_brain, [bad_frame_requirement], bad_frame_evidence,
        surface_registry=bad_registry, impact_seeds=bad_seeds,
        mandatory_core=bad_core,
    )
    bad_frame_check = validate_impact_decision_frame(bad_frame)

    # Case B selects INSPECT_ONLY in every structurally valid slot despite the
    # ready frame exposing MUST_CHANGE.  The choice gate must reject it and no
    # downstream role is involved.
    inspect_choices = {"decisions": []}
    for slot in frame.get("decision_slots", []):
        if str(slot.get("slot_id")) not in set(projection.get("required_choice_slot_ids", [])):
            continue
        if "INSPECT_ONLY" not in slot.get("allowed_decisions", []):
            continue
        inspect_choices["decisions"].append({
            "slot_id": slot.get("slot_id"),
            "decision": "INSPECT_ONLY",
            "chosen_target": slot.get("surface_id"),
            "reason_code": "INSPECT_CURRENT_SURFACE",
            "bounded_rationale": "Inspect the verified current surface.",
        })
    inspect_check = validate_impact_decision_choices(
        inspect_choices, frame, projection=projection,
    )
    challenge_types = {
        item.get("challenge_type")
        for item in deterministic_challenges(
            compiled.get("impact_map", {}), requirements, evidence, registry,
        )
        if isinstance(item, dict)
    } if compiled.get("valid") else {"COMPILE_INVALID"}

    # Case D contains preservation authority only.  It must be satisfiable by
    # inherited preservation or PRESERVATION_ONLY without a forced mutation.
    preserve_requirement = [{
        "requirement_id": "REQ-SELF-PRESERVE",
        "text": "Preserve the current pause-state owner.",
        "provenance": USER_STATED,
        "status": "active",
    }]
    preserve_evidence = [{
        "evidence_id": "REPO-SELF-PRESERVE-OWNER",
        "category": "CURRENT_STATE_OWNER",
        "path": "src/pause_controller.js",
        "symbol": "PauseController",
        "fact": "PauseController owns pause state",
        "file_sha256": "f" * 64,
    }]
    preserve_brain = {
        "project_id": "self-test-project",
        "task_id": "self-test-preserve",
        "task_goal": {"text": preserve_requirement[0]["text"]},
        "current_owners": [{
            "text": "PauseController owns pause state",
            "path": "src/pause_controller.js", "symbol": "PauseController",
            "category": "CURRENT_STATE_OWNER",
            "evidence_ids": ["REPO-SELF-PRESERVE-OWNER"],
        }],
        "current_state_ownership": [{
            "text": "PauseController owns pause state",
            "path": "src/pause_controller.js", "symbol": "PauseController",
            "category": "CURRENT_STATE_OWNER",
            "evidence_ids": ["REPO-SELF-PRESERVE-OWNER"],
        }],
        "preservation_constraints": [{
            "text": preserve_requirement[0]["text"],
            "requirement_ids": ["REQ-SELF-PRESERVE"],
        }],
    }
    preserve_registry = build_canonical_surface_registry(preserve_brain, preserve_evidence)
    preserve_seeds = build_impact_seeds(
        preserve_brain, preserve_requirement, preserve_evidence,
        registry=preserve_registry,
    )
    preserve_core = build_canonical_mandatory_planning_core({
        "project_id": preserve_brain["project_id"],
        "task_id": preserve_brain["task_id"],
        "task_goal": preserve_brain["task_goal"],
        "requirements": preserve_requirement,
        "surfaces": preserve_registry.get("surfaces", []),
        "impact_seeds": preserve_seeds,
        "preservation_constraints": preserve_brain["preservation_constraints"],
    })
    preserve_frame = build_impact_decision_frame(
        preserve_brain, preserve_requirement, preserve_evidence,
        surface_registry=preserve_registry, impact_seeds=preserve_seeds,
        mandatory_core=preserve_core,
    )
    preserve_choices = deterministic_impact_decision_choices(preserve_frame)
    preserve_compiled = compile_impact_map_from_choices(
        preserve_frame, preserve_choices, preserve_requirement, preserve_evidence,
        surface_registry=preserve_registry, impact_seeds=preserve_seeds,
    )
    checks.update({
        "case_a_live_bad_frame": (
            bad_frame_check.get("status") == IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP
            and bad_frame_check.get("model_calls") == 0
            and bool(bad_frame_check.get("uncovered_obligations"))
        ),
        "case_b_weak_bad_choice": (
            inspect_check.get("status", "").startswith(IMPACT_CHOICE_REQUIREMENT_GAP)
            and inspect_check.get("model_calls") == 0
            and bool(inspect_check.get("uncovered_obligations"))
        ),
        "case_c_valid_choice_assignment": (
            compiled.get("valid") is True
            and compiled.get("semantic_validation", {}).get("valid") is True
            and bool(compiled.get("impact_map", {}).get("obligation_assignments"))
            and "REQUIREMENT_GAP" not in challenge_types
        ),
        "case_d_preservation_only": (
            preserve_compiled.get("valid") is True
            and all(
                item.get("disposition") != "MUST_CHANGE"
                for item in preserve_compiled.get("impact_map", {}).get("impacts", [])
            )
        ),
    })
    return {
        "passed": all(checks.values()), "checks": checks, "model_calls": 0,
        "frame": frame, "choices": choices, "compiled": compiled,
        "diagnostics": {
            "frame_hash": frame.get("frame_hash"),
            "choice_hash": choice_check.get("choice_hash"),
            "slot_count": len(frame.get("decision_slots", []) or []),
            "packet_chars": packet.get("packet_chars"),
        },
    }


run_impact_decision_frame_self_test = impact_decision_frame_self_test


def normalize_new_surface_proposals(values):
    result = []
    for index, item in enumerate(list(values or [])[:4], 1):
        if not isinstance(item, dict):
            continue
        result.append({
            "proposal_id": _compact(item.get("proposal_id") or f"NEW-{index:03d}", 80),
            "kind": _compact(item.get("kind") or "NEW_SURFACE", 80),
            "requirement_ids": _bounded_ids(item.get("requirement_ids"), 6),
            "reason_existing_surfaces_insufficient": _compact(
                item.get("reason_existing_surfaces_insufficient"), MAX_TEXT_CHARS,
            ),
            "parent_scope": _compact(item.get("parent_scope"), 240),
            "intended_responsibility": _compact(item.get("intended_responsibility"), MAX_TEXT_CHARS),
            "verification_responsibility": _compact(
                item.get("verification_responsibility"), MAX_TEXT_CHARS,
            ),
            "provenance": DERIVED_PLAN_DECISION,
        })
    return result


_CANONICAL_IMPACT_ROOT_FIELDS = frozenset({
    "task_goal", "impacts", "integration_verification", "insufficient_evidence",
    "new_surface_proposals",
})
_CANONICAL_IMPACT_INTERNAL_ROOT_FIELDS = frozenset({
    "version", "bounds", "provenance", "requirement_obligation_ledger",
    "semantic_obligation_coverage", "behavior_anchor_closure_actions",
    "challenge_lifecycle", "obligation_closure_actions", "prohibition_constraints",
    "deterministic_behavior_anchor_promotions", "obligation_impacts_synthesized",
    "preservation_obligations_closed", "reuse_obligations_closed",
    "test_obligations_closed", "prohibition_obligations_closed",
    "impact_challenges_applicable", "impact_challenges_non_applicable",
    "challenge_effects_applied", "challenge_effects_suppressed",
    "challenges_resolved_post_reconciliation", "challenges_remaining_open",
})
_CANONICAL_IMPACT_ENTRY_FIELDS = frozenset({
    "impact_id", "surface_id", "disposition", "action", "interfaces_to_reuse",
    "verification", "new_surface_proposal_ids", "requirement_ids", "reason",
    "preserve", "test_contract",
})
_KNOWN_IMPACT_ENTRY_COMPAT_FIELDS = frozenset({
    # These fields are already consumed by the existing Stage 3 normalizer or
    # hydrator.  They are retained only as explicit compatibility fields; the
    # canonical semantic validator remains authoritative.
    "impact_kind", "necessity_status", "candidate_change", "local_verification",
    "local_test_contract", "existing_interfaces_to_reuse", "interface_surface_ids",
    "reusable_interfaces", "path", "symbols", "component", "existing_owner",
    "repository_evidence_ids",
    "local_preservation_constraints", "prohibition_constraints", "closure_metadata",
    "model_path", "model_component", "model_symbols", "model_existing_owner",
    "model_repository_evidence_ids", "model_surface_id", "canonical_surface_id",
    "seed_id", "seed_surface_id", "surface_kind", "surface_role", "owner_surface_id",
    "provenance",
})
_LEGACY_IMPACT_ENTRY_ALIAS_FIELDS = frozenset({
    "source_requirement_ids", "source_requirements", "preservation_promises",
    "verification_contracts", "reused_interfaces", "canonical_interface_reuses",
    "canonical_interface_reuse",
})
_KNOWN_EMPTY_LEGACY_IMPACT_ROOT_FIELDS = frozenset({
    "canonical_interface_reuses", "canonical_interface_reuse", "reused_interfaces",
    "preservation_promises", "verification_contracts", "verification_test_contracts",
})
_LEGACY_IMPACT_ROOT_FIELDS = frozenset({
    "impact_decisions", "NEW_SURFACE_PROPOSAL",
}) | _KNOWN_EMPTY_LEGACY_IMPACT_ROOT_FIELDS
_CANONICAL_NEW_SURFACE_FIELDS = frozenset({
    "proposal_id", "kind", "requirement_ids", "reason_existing_surfaces_insufficient",
    "parent_scope", "intended_responsibility", "verification_responsibility",
})
_IMPACT_PLACEHOLDER_IDS = frozenset({"", "n/a", "na", "unknown", "none", "null"})


def _canonicalization_string_list(value, field_name, errors):
    """Normalize only a string or string-list representation.

    The helper is intentionally strict for objects, numbers, and nested
    structures.  A scalar string is the one harmless representation change
    supported by the impact-map compatibility boundary.
    """
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)):
        errors.append(f"{field_name} must be a string or list of strings")
        return None
    result = []
    for item in values:
        if not isinstance(item, str):
            errors.append(f"{field_name} must contain only strings")
            return None
        text = item.strip()
        if not text:
            errors.append(f"{field_name} must not contain empty strings")
            return None
        result.append(text)
    return result


def _merge_impact_string_list(output, item, canonical_name, aliases, errors):
    """Merge one canonical list field and explicit legacy aliases."""
    values = None
    present = []
    for name in (canonical_name,) + tuple(aliases):
        if name not in item:
            continue
        normalized = _canonicalization_string_list(item.get(name), name, errors)
        if normalized is not None:
            present.append((name, normalized))
    for name, normalized in present:
        if values is not None and normalized != values:
            errors.append(
                f"conflicting values for {canonical_name}: {name} disagrees with another alias"
            )
            continue
        values = normalized
    if present:
        output[canonical_name] = values if values is not None else []


def _merge_impact_text(output, item, canonical_name, aliases, errors):
    """Merge one text field while rejecting contradictory aliases."""
    values = []
    for name in (canonical_name,) + tuple(aliases):
        if name not in item:
            continue
        value = item.get(name)
        if not isinstance(value, str):
            errors.append(f"{name} must be a string")
            continue
        text = value.strip()
        values.append((name, text))
    if not values:
        return
    chosen = values[0][1]
    if any(text != chosen for _, text in values[1:]):
        errors.append(f"conflicting values for {canonical_name}")
    output[canonical_name] = chosen


def _canonicalize_impact_entry(item, inherited_impact_id=None, location="impact", errors=None):
    """Map one explicitly supported legacy decision to the canonical entry.

    This function changes field names and envelopes only.  It never creates a
    requirement, surface, evidence reference, action, or proposal body.
    """
    errors = errors if errors is not None else []
    if not isinstance(item, dict):
        errors.append(f"{location} must be an object")
        return None
    allowed = (
        _CANONICAL_IMPACT_ENTRY_FIELDS
        | _KNOWN_IMPACT_ENTRY_COMPAT_FIELDS
        | _LEGACY_IMPACT_ENTRY_ALIAS_FIELDS
    )
    unknown = sorted(set(item) - allowed)
    if unknown:
        errors.append(f"{location} contains unrecognized fields: {', '.join(unknown[:6])}")
    output = {}

    raw_id = item.get("impact_id")
    if raw_id is not None:
        if not isinstance(raw_id, str):
            errors.append(f"{location}.impact_id must be a string")
        else:
            raw_id = raw_id.strip()
    inherited = str(inherited_impact_id or "").strip()
    if raw_id and inherited and raw_id != inherited:
        errors.append(f"{location}.impact_id conflicts with its top-level impact key")
    if inherited:
        output["impact_id"] = inherited
    elif raw_id is not None:
        output["impact_id"] = raw_id

    _merge_impact_string_list(
        output, item, "requirement_ids", ("source_requirement_ids", "source_requirements"), errors,
    )
    _merge_impact_string_list(
        output, item, "interfaces_to_reuse", ("interface_surface_ids", "reusable_interfaces"), errors,
    )
    _merge_impact_string_list(
        output, item, "verification", ("local_verification",), errors,
    )
    _merge_impact_string_list(
        output, item, "test_contract", ("local_test_contract",), errors,
    )
    for field in (
        "preserve", "new_surface_proposal_ids", "repository_evidence_ids", "symbols",
        "existing_interfaces_to_reuse", "local_preservation_constraints",
        "prohibition_constraints",
    ):
        if field in item:
            normalized = _canonicalization_string_list(item.get(field), field, errors)
            if normalized is not None:
                output[field] = normalized

    for field in (
        "surface_id", "impact_kind", "necessity_status", "path", "component",
        "existing_owner", "model_path", "model_existing_owner",
    ):
        if field in item:
            value = item.get(field)
            if value is not None and not isinstance(value, str):
                errors.append(f"{location}.{field} must be a string")
            else:
                output[field] = value.strip() if isinstance(value, str) else value
    for field in (
        "model_component", "model_surface_id", "canonical_surface_id", "seed_id",
        "seed_surface_id", "surface_kind", "surface_role", "owner_surface_id", "provenance",
    ):
        if field in item:
            output[field] = copy.deepcopy(item.get(field))
    for field in ("closure_metadata", "model_symbols", "model_repository_evidence_ids"):
        if field in item:
            output[field] = copy.deepcopy(item.get(field))

    _merge_impact_text(output, item, "action", ("candidate_change",), errors)
    if "reason" in item:
        value = item.get("reason")
        if not isinstance(value, str):
            errors.append(f"{location}.reason must be a string")
        else:
            output["reason"] = value.strip()

    disposition_present = "disposition" in item
    if disposition_present:
        disposition = item.get("disposition")
        if not isinstance(disposition, str):
            errors.append(f"{location}.disposition must be a string")
        else:
            output["disposition"] = disposition.strip().upper()

    action = output.get("action")
    action_disposition = action.strip().upper() if isinstance(action, str) else ""
    if action_disposition in DISPOSITIONS:
        current = output.get("disposition")
        if current and current != action_disposition:
            errors.append(f"{location}.action disposition conflicts with disposition")
        else:
            output["disposition"] = action_disposition
        # Captured legacy planners put the decision token in ``action`` and
        # the actual semantic explanation in ``reason``.  Preserve the token
        # as disposition and use the explanation as the canonical action when
        # it exists; this is a representation change, not semantic invention.
        if isinstance(output.get("reason"), str) and output["reason"].strip():
            output["action"] = output["reason"].strip()
    elif not disposition_present and any(
        field in output for field in ("impact_kind", "necessity_status")
    ):
        output["disposition"] = _disposition_for_impact(output)

    for field in (
        "preservation_promises", "verification_contracts", "reused_interfaces",
        "canonical_interface_reuses", "canonical_interface_reuse",
    ):
        if field in item:
            value = item.get(field)
            if value not in (None, [], ""):
                errors.append(f"{location}.{field} has no unambiguous canonical destination")

    return output


def _canonicalize_new_surface_proposals(value, errors):
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append("new_surface_proposals must be a list")
        return []
    if len(value) > 4:
        errors.append("new_surface_proposals bound exceeded")
    result = []
    for index, proposal in enumerate(value, 1):
        if not isinstance(proposal, dict):
            errors.append(f"new_surface_proposals[{index}] must be an object")
            continue
        unknown = sorted(set(proposal) - _CANONICAL_NEW_SURFACE_FIELDS)
        if unknown:
            errors.append(
                f"new_surface_proposals[{index}] contains unrecognized fields: {', '.join(unknown[:6])}"
            )
        normalized = copy.deepcopy(proposal)
        missing = sorted(_CANONICAL_NEW_SURFACE_FIELDS - set(proposal))
        if missing:
            errors.append(
                f"new_surface_proposals[{index}] is missing canonical fields: {', '.join(missing[:6])}"
            )
        if "requirement_ids" in proposal:
            refs = _canonicalization_string_list(
                proposal.get("requirement_ids"),
                f"new_surface_proposals[{index}].requirement_ids", errors,
            )
            if refs is not None:
                normalized["requirement_ids"] = refs
        result.append(normalized)
    return result


def _impact_map_result(status, source_envelope, canonical_candidate=None, errors=None,
                       canonicalization="FAILED"):
    return {
        "valid": status == "VALID",
        "status": status,
        "reason_code": None if status == "VALID" else status,
        "errors": list(errors or [])[:16],
        "source_envelope": source_envelope,
        "canonicalization": canonicalization,
        "canonical_candidate": copy.deepcopy(canonical_candidate)
        if canonical_candidate is not None else None,
    }


def canonicalize_impact_map_candidate(candidate):
    """Return one canonical impact-map candidate before semantic validation.

    Supported non-canonical envelopes are limited to the formats observed in
    the diagnostic run: ``impact_decisions`` lists and top-level IMPACT IDs.
    Empty legacy metadata is harmless and ignored; non-empty metadata without
    a canonical semantic destination is rejected rather than discarded.
    """
    if not isinstance(candidate, dict):
        return _impact_map_result(
            IMPACT_MAP_PARSE_INVALID, "NON_OBJECT",
            errors=["impact-map response must be a JSON object"],
        )
    if _forbidden_context_key(candidate):
        forbidden = _forbidden_context_key(candidate)
        return _impact_map_result(
            IMPACT_MAP_CANONICALIZATION_FAILED, "FORBIDDEN_CONTEXT",
            errors=[f"raw context field is forbidden: {forbidden}"],
        )

    errors = []
    root = candidate
    has_impacts = "impacts" in root
    has_impact_decisions = "impact_decisions" in root
    direct_fields = set(root).intersection(_CANONICAL_IMPACT_ENTRY_FIELDS)
    keyed_ids = sorted(
        (key for key in root if _IMPACT_ID_RE.fullmatch(str(key))),
        key=lambda value: (int(_IMPACT_ID_RE.fullmatch(str(value)).group(1)), str(value)),
    )
    if has_impacts:
        source_envelope = "CANONICAL_ALREADY"
        raw_impacts = root.get("impacts")
        if not isinstance(raw_impacts, list):
            errors.append("impacts must be a list")
            raw_impacts = []
        if has_impact_decisions and root.get("impact_decisions") not in (None, [], ""):
            errors.append("impacts and impact_decisions cannot both contain decisions")
        if keyed_ids:
            errors.append("canonical impacts cannot be mixed with top-level impact IDs")
        if direct_fields:
            errors.append(
                "canonical impacts cannot be mixed with top-level direct-decision fields: "
                + ", ".join(sorted(direct_fields)[:6])
            )
    elif has_impact_decisions:
        source_envelope = "LEGACY_IMPACT_DECISIONS"
        raw_impacts = root.get("impact_decisions")
        if not isinstance(raw_impacts, list):
            errors.append("impact_decisions must be a list")
            raw_impacts = []
        if keyed_ids or direct_fields:
            errors.append("impact_decisions cannot be mixed with another impact envelope")
    elif keyed_ids:
        source_envelope = "LEGACY_TOP_LEVEL_IMPACT_IDS"
        raw_impacts = [(key, root.get(key)) for key in keyed_ids]
        if direct_fields:
            errors.append("top-level impact IDs cannot be mixed with direct-decision fields")
    elif "impact_id" in root:
        source_envelope = "DIRECT_DECISION"
        raw_impacts = [{
            key: value for key, value in root.items()
            if key in (
                _CANONICAL_IMPACT_ENTRY_FIELDS
                | _KNOWN_IMPACT_ENTRY_COMPAT_FIELDS
                | _LEGACY_IMPACT_ENTRY_ALIAS_FIELDS
            )
        }]
    else:
        return _impact_map_result(
            IMPACT_MAP_UNSUPPORTED_ENVELOPE, "UNKNOWN",
            errors=["no supported canonical impact-map envelope was found"],
        )

    allowed_root = (
        _CANONICAL_IMPACT_ROOT_FIELDS
        | _CANONICAL_IMPACT_INTERNAL_ROOT_FIELDS
        | _LEGACY_IMPACT_ROOT_FIELDS
    )
    if source_envelope == "LEGACY_TOP_LEVEL_IMPACT_IDS":
        allowed_root = allowed_root | set(keyed_ids)
    if source_envelope == "DIRECT_DECISION":
        allowed_root = (
            allowed_root | _CANONICAL_IMPACT_ENTRY_FIELDS
            | _KNOWN_IMPACT_ENTRY_COMPAT_FIELDS | _LEGACY_IMPACT_ENTRY_ALIAS_FIELDS
        )
    unknown_root = sorted(set(root) - allowed_root)
    if unknown_root:
        errors.append("unrecognized top-level fields: " + ", ".join(unknown_root[:6]))

    canonical = {}
    for field in _CANONICAL_IMPACT_ROOT_FIELDS - {"impacts", "new_surface_proposals"}:
        if field in root:
            canonical[field] = copy.deepcopy(root.get(field))
    for field in _CANONICAL_IMPACT_INTERNAL_ROOT_FIELDS:
        if field in root:
            canonical[field] = copy.deepcopy(root.get(field))
    if "new_surface_proposals" in root:
        canonical["new_surface_proposals"] = _canonicalize_new_surface_proposals(
            root.get("new_surface_proposals"), errors,
        )

    if "verification_test_contracts" in root or "verification_contracts" in root:
        aliases = []
        for field in ("verification_test_contracts", "verification_contracts"):
            if field in root:
                aliases.append((field, _canonicalization_string_list(root.get(field), field, errors)))
        nonempty = [(field, value) for field, value in aliases if value]
        if nonempty:
            selected = nonempty[0][1]
            if any(value != selected for _, value in nonempty[1:]):
                errors.append("verification contract aliases disagree")
            if "integration_verification" in canonical and canonical["integration_verification"] != selected:
                errors.append("integration_verification conflicts with verification contract alias")
            else:
                canonical["integration_verification"] = selected
    if "integration_verification" in root:
        values = _canonicalization_string_list(
            root.get("integration_verification"), "integration_verification", errors,
        )
        if values is not None:
            canonical["integration_verification"] = values
    if "insufficient_evidence" in root:
        values = _canonicalization_string_list(
            root.get("insufficient_evidence"), "insufficient_evidence", errors,
        )
        if values is not None:
            canonical["insufficient_evidence"] = values

    for field in _KNOWN_EMPTY_LEGACY_IMPACT_ROOT_FIELDS:
        if field in root and root.get(field) not in (None, [], ""):
            if field not in {"verification_contracts", "verification_test_contracts"}:
                errors.append(f"{field} has no unambiguous canonical destination")
    if "NEW_SURFACE_PROPOSAL" in root and root.get("NEW_SURFACE_PROPOSAL") not in (None, [], "", {}):
        errors.append(
            "NEW_SURFACE_PROPOSAL has no canonical proposal contract and cannot be safely mapped"
        )

    entries = []
    if source_envelope == "LEGACY_TOP_LEVEL_IMPACT_IDS":
        for key, item in raw_impacts:
            entry = _canonicalize_impact_entry(
                item, inherited_impact_id=str(key), location=str(key), errors=errors,
            )
            if entry is not None:
                entries.append(entry)
    else:
        for index, item in enumerate(raw_impacts, 1):
            entry = _canonicalize_impact_entry(
                item, location=f"impacts[{index}]", errors=errors,
            )
            if entry is not None:
                entries.append(entry)
    canonical["impacts"] = entries

    if errors:
        status = (
            IMPACT_MAP_UNSUPPORTED_ENVELOPE
            if source_envelope in {"UNKNOWN", "LEGACY_TOP_LEVEL_IMPACT_IDS", "LEGACY_IMPACT_DECISIONS"}
            and any("unrecognized" in error or "no canonical" in error for error in errors)
            else IMPACT_MAP_CANONICALIZATION_FAILED
        )
        return _impact_map_result(status, source_envelope, errors=errors)
    changed = source_envelope != "CANONICAL_ALREADY" or canonical != candidate
    return _impact_map_result(
        "VALID", source_envelope, canonical_candidate=canonical,
        canonicalization="APPLIED" if changed else "NOT_NEEDED",
    )


def normalize_impact_map(candidate, authoritative=False):
    canonicalization = canonicalize_impact_map_candidate(candidate)
    if canonicalization.get("valid"):
        candidate = canonicalization.get("canonical_candidate") or {}
    candidate = candidate if isinstance(candidate, dict) else {}
    # A provider may return one decision object before it learns the enclosing
    # map envelope.  Treat that as a one-decision candidate so the normal
    # per-decision validator can decide whether it is usable.
    if "impacts" not in candidate and candidate.get("impact_id"):
        candidate = {"impacts": [candidate], **{
            key: candidate[key] for key in (
                "task_goal", "integration_verification", "insufficient_evidence",
                "new_surface_proposals",
            ) if key in candidate
        }}
    goal = candidate.get("task_goal", "")
    if isinstance(goal, dict):
        goal = goal.get("text", "")
    impacts = []
    raw_impacts = candidate.get("impacts", [])
    if not isinstance(raw_impacts, (list, tuple)):
        raw_impacts = []
    for index, item in enumerate(list(raw_impacts)[:MAX_IMPACT_ENTRIES], 1):
        if not isinstance(item, dict):
            continue
        disposition = _disposition_for_impact(item)
        kind = _impact_kind_for_disposition(disposition, item.get("impact_kind"))
        legacy_necessity = str(item.get("necessity_status", "")).upper()
        necessity = {
            "MUST_CHANGE": "MUST_CHANGE",
            "INTERFACE_REUSE": "CANDIDATE",
            "TEST_CHANGE": "CANDIDATE",
            "PRESERVATION_ONLY": "PRESERVATION_ONLY",
            "VERIFY_ONLY": "CANDIDATE",
            "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE",
        }.get(disposition, str(item.get("necessity_status", "")).upper() or "CANDIDATE")
        if legacy_necessity in NECESSITY_STATUSES and "disposition" not in item:
            necessity = legacy_necessity
        path = _compact(item.get("path"), 240)
        symbols = _bounded_strings(_list_value(item.get("symbols")), 6, 160)
        interfaces = _bounded_strings(
            _list_value(item.get("existing_interfaces_to_reuse")), 6, 180,
        )
        interface_surface_ids = _bounded_ids(
            _list_value(item.get("interfaces_to_reuse") or item.get("interface_surface_ids")), 6,
        )
        action = _compact(
            item.get("action") or item.get("candidate_change") or item.get("reason"),
            MAX_TEXT_CHARS,
        )
        verification = _bounded_strings(
            _list_value(item.get("verification") or item.get("local_verification")
                        or item.get("test_contract") or item.get("local_test_contract")),
            6, 300,
        )
        preserve = _bounded_strings(_list_value(item.get("preserve")), 6, 300)
        local_preservation = _bounded_strings(
            _list_value(item.get("local_preservation_constraints")), 8, 300,
        )
        prohibitions = _bounded_strings(
            _list_value(item.get("prohibition_constraints")), 6, 320,
        )
        requirement_ids = _bounded_ids(
            _list_value(item.get("requirement_ids")), MAX_REQUIREMENT_REFS_PER_IMPACT,
        )
        evidence_ids = _bounded_ids(
            _list_value(item.get("repository_evidence_ids")), MAX_EVIDENCE_REFS_PER_IMPACT,
        )
        proposal_ids = _bounded_ids(_list_value(item.get("new_surface_proposal_ids")), 4)
        model_surface_id = _compact(item.get("surface_id"), 80)
        value = {
            "impact_id": _compact(item.get("impact_id") or f"IMP-{index:03d}", 80),
            "surface_id": model_surface_id,
            "model_surface_id": model_surface_id,
            "disposition": disposition,
            "component": _compact(item.get("component") or item.get("path") or "project surface", 180),
            "path": path,
            "symbols": symbols,
            "impact_kind": kind,
            "requirement_ids": requirement_ids,
            "repository_evidence_ids": evidence_ids,
            "reason": _compact(item.get("reason") or item.get("action"), MAX_TEXT_CHARS),
            "existing_owner": _compact(item.get("existing_owner"), 180),
            "existing_interfaces_to_reuse": interfaces,
            "interfaces_to_reuse": interface_surface_ids,
            "interface_surface_ids": interface_surface_ids,
            "preserve": preserve,
            "local_preservation_constraints": local_preservation,
            "prohibition_constraints": prohibitions,
            "candidate_change": action,
            "action": action,
            "local_verification": verification,
            "verification": verification,
            "test_contract": verification,
            "local_test_contract": verification,
            "necessity_status": necessity,
            "new_surface_proposal_ids": proposal_ids,
            "provenance": DERIVED_PLAN_DECISION,
        }
        if isinstance(item.get("closure_metadata"), dict):
            value["closure_metadata"] = {
                "closure_type": _compact(item["closure_metadata"].get("closure_type"), 80),
                "requirement_ids": _bounded_ids(item["closure_metadata"].get("requirement_ids"), 6),
                "surface_id": _compact(item["closure_metadata"].get("surface_id"), 80),
                "seed_id": _compact(item["closure_metadata"].get("seed_id"), 80),
                "provenance": DERIVED_PLAN_DECISION,
            }
        # Keep model-authored identity only in explicitly non-authoritative
        # audit fields.  Hydrated maps replace the ordinary identity fields.
        if not authoritative:
            value["model_path"] = path
            value["model_component"] = _compact(item.get("component"), 180)
            value["model_symbols"] = symbols
            value["model_existing_owner"] = _compact(item.get("existing_owner"), 180)
            value["model_repository_evidence_ids"] = list(evidence_ids)
        impacts.append(value)
    normalized = {
        "version": 1,
        "task_goal": _compact(goal, 1000),
        "impacts": impacts,
        "integration_verification": _bounded_strings(
            _list_value(candidate.get("integration_verification")), 10, 320,
        ),
        "insufficient_evidence": _bounded_strings(
            _list_value(candidate.get("insufficient_evidence")), 6, 320,
        ),
        "new_surface_proposals": normalize_new_surface_proposals(
            candidate.get("new_surface_proposals"),
        ),
        "bounds": {
            "max_impact_entries": MAX_IMPACT_ENTRIES,
            "max_requirement_refs_per_impact": MAX_REQUIREMENT_REFS_PER_IMPACT,
            "max_evidence_refs_per_impact": MAX_EVIDENCE_REFS_PER_IMPACT,
        },
        "provenance": DERIVED_PLAN_DECISION,
    }
    for key in (
        "requirement_obligation_ledger", "semantic_obligation_coverage",
        "behavior_anchor_closure_actions", "challenge_lifecycle",
        "obligation_closure_actions", "prohibition_constraints",
    ):
        if key in candidate:
            normalized[key] = copy.deepcopy(candidate.get(key))
    for key in (
        "deterministic_behavior_anchor_promotions", "obligation_impacts_synthesized",
        "preservation_obligations_closed", "reuse_obligations_closed",
        "test_obligations_closed", "prohibition_obligations_closed",
        "impact_challenges_applicable", "impact_challenges_non_applicable",
        "challenge_effects_applied", "challenge_effects_suppressed",
        "challenges_resolved_post_reconciliation", "challenges_remaining_open",
    ):
        normalized[key] = int(candidate.get(key, 0) or 0)
    return normalized


def _normal_path(value):
    return str(value or "").replace("\\", "/").strip()


def _surface_evidence_by_id(evidence):
    return {
        item["evidence_id"]: item
        for item in bounded_evidence(evidence, MAX_CANONICAL_SURFACES * 2)
        if item.get("evidence_id")
    }


def validate_canonical_surface_registry(registry, evidence=None):
    """Validate registry shape and prove that every surface is evidence-backed."""
    value = registry if isinstance(registry, dict) else {}
    errors = []
    surfaces = list(value.get("surfaces", []) or [])
    if value.get("version") != 1:
        errors.append("canonical surface registry version is unsupported")
    if len(surfaces) > MAX_CANONICAL_SURFACES:
        errors.append("canonical surface registry bound exceeded")
    evidence_by_id = _surface_evidence_by_id(evidence or [])
    seen = set()
    for surface in surfaces:
        if not isinstance(surface, dict):
            errors.append("surface entry must be an object")
            continue
        surface_id = str(surface.get("surface_id", ""))
        if not _SURFACE_ID_RE.match(surface_id) or surface_id in seen:
            errors.append(f"{surface_id or '<missing>'}: invalid or duplicate surface ID")
        seen.add(surface_id)
        if surface.get("kind") not in CANONICAL_SURFACE_KINDS:
            errors.append(f"{surface_id}: invalid surface kind")
        if surface.get("role") not in CANONICAL_SURFACE_ROLES:
            errors.append(f"{surface_id}: invalid surface role")
        path = _normal_path(surface.get("path"))
        if not path:
            errors.append(f"{surface_id}: verified path is required")
        if _normal_path(surface.get("verified_path", path)) != path:
            errors.append(f"{surface_id}: verified_path is not canonical")
        if str(surface.get("verified_symbol", surface.get("symbol", ""))) != str(surface.get("symbol", "")):
            errors.append(f"{surface_id}: verified_symbol is not canonical")
        refs = list(surface.get("evidence_ids", []) or [])
        if not refs or len(refs) > MAX_SURFACE_EVIDENCE_IDS:
            errors.append(f"{surface_id}: bounded evidence references are required")
        if evidence_by_id:
            for evidence_id in refs:
                fact = evidence_by_id.get(str(evidence_id))
                if not fact:
                    errors.append(f"{surface_id}: unknown evidence reference {evidence_id}")
                    continue
                if _normal_path(fact.get("path")) != path:
                    errors.append(f"{surface_id}: evidence path does not match verified path")
        if surface.get("provenance") != REPOSITORY_EVIDENCE:
            errors.append(f"{surface_id}: repository provenance is required")
    by_id = canonical_surface_by_id(value)
    for surface in surfaces:
        owner_id = surface.get("owner_surface_id")
        if owner_id and (
            owner_id not in by_id or by_id[owner_id].get("kind") != "OWNER"
        ):
            errors.append(f"{surface.get('surface_id')}: invalid owner surface relation")
    expected_ids = [str(item.get("surface_id")) for item in surfaces if item.get("surface_id")]
    if list(value.get("surface_ids", expected_ids) or []) != expected_ids:
        errors.append("surface_ids index is not canonical")
    return {
        "valid": not errors,
        "errors": errors[:24],
        "surface_count": len(surfaces),
        "evidence_count": sum(len(item.get("evidence_ids", []) or []) for item in surfaces),
    }


def _surface_symbols_supported(surface, model_symbols, evidence_by_id):
    """Check an optional model identity claim without giving it authority."""
    symbols = [str(item).strip() for item in list(model_symbols or []) if str(item).strip()]
    if not symbols:
        return True
    canonical = str(surface.get("symbol") or "").strip()
    allowed = {canonical} if canonical else set()
    for evidence_id in surface.get("evidence_ids", []) or []:
        fact = evidence_by_id.get(str(evidence_id))
        if fact and fact.get("symbol"):
            allowed.add(str(fact.get("symbol")).strip())
    if surface.get("kind") == "OWNER" and canonical:
        prefix = canonical + "."
        return all(item in allowed or item.startswith(prefix) for item in symbols)
    return all(item in allowed for item in symbols)


def _path_symbols_supported(path, model_symbols, evidence_by_id):
    symbols = {str(item.get("symbol") or "").strip() for item in evidence_by_id.values()
               if _normal_path(item.get("path")) == _normal_path(path) and item.get("symbol")}
    if not symbols:
        return False
    owner_bases = {_surface_symbol_base(item) for item in symbols}
    return all(
        str(item).strip() in symbols
        or any(str(item).strip().startswith(base + ".") for base in owner_bases if base)
        for item in list(model_symbols or [])
    )


def surface_evidence_supports(surface, evidence_ids, evidence=None):
    """Return whether evidence IDs belong to and semantically support a surface."""
    if not isinstance(surface, dict):
        return False
    refs = {str(item) for item in list(evidence_ids or [])}
    owned = {str(item) for item in list(surface.get("evidence_ids", []) or [])}
    if not refs or not refs.issubset(owned):
        return False
    evidence_by_id = _surface_evidence_by_id(evidence or [])
    path = _normal_path(surface.get("path"))
    canonical_symbol = str(surface.get("symbol") or "").strip()
    for evidence_id in refs:
        fact = evidence_by_id.get(evidence_id)
        if not fact or _normal_path(fact.get("path")) != path:
            return False
        symbol = str(fact.get("symbol") or "").strip()
        if canonical_symbol:
            if surface.get("kind") == "OWNER":
                if _surface_symbol_base(symbol) != _surface_symbol_base(canonical_symbol):
                    return False
            elif symbol and symbol != canonical_symbol:
                return False
    return True


def _surface_for_legacy_identity(item, surfaces, evidence_by_id=None):
    """Map an old exact path/symbol claim only for deterministic compatibility."""
    model_path = _normal_path(item.get("model_path") or item.get("path"))
    if not model_path:
        return None
    model_symbols = list(item.get("model_symbols") or item.get("symbols") or [])
    candidates = [
        surface for surface in surfaces
        if _normal_path(surface.get("path")) == model_path
    ]
    if len(candidates) == 1:
        return candidates[0]
    model_component = str(item.get("model_component") or item.get("component") or "").strip()
    scored = []
    for surface in candidates:
        evidence_index = evidence_by_id or {}
        if not (
            _surface_symbols_supported(surface, model_symbols, evidence_index)
            or _path_symbols_supported(surface.get("path"), model_symbols, evidence_index)
        ):
            continue
        score = sum(
            1 for symbol in model_symbols
            if str(symbol) == str(surface.get("symbol") or "")
        )
        if model_component and model_component.casefold() == str(surface.get("symbol") or "").casefold():
            score += 3
        if surface.get("kind") == "OWNER" and model_component:
            score += 1
        scored.append((score, str(surface.get("surface_id")), surface))
    if not scored:
        return None
    scored.sort(key=lambda row: (-row[0], row[1]))
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][2]


def _new_surface_proposal_justified(proposal):
    text = str(proposal.get("reason_existing_surfaces_insufficient") or "").casefold()
    return bool(text) and bool(re.search(
        r"insufficient|not represented|no existing|missing|cannot .* existing|cannot safely",
        text,
    ))


def validate_new_surface_proposals(proposals, requirements, registry):
    req_ids = {item["requirement_id"] for item in active_requirements(requirements)}
    existing = canonical_surface_by_id(registry)
    accepted, rejected = [], []
    seen = set()
    for proposal in list(proposals or [])[:4]:
        value = copy.deepcopy(proposal)
        errors = []
        proposal_id = str(value.get("proposal_id", ""))
        if not _NEW_SURFACE_ID_RE.match(proposal_id) or proposal_id in seen:
            errors.append("invalid or duplicate proposal ID")
        seen.add(proposal_id)
        refs = {str(item) for item in value.get("requirement_ids", [])}
        if not refs or not refs.issubset(req_ids):
            errors.append("proposal must cite active Source Requirement IDs")
        if not value.get("kind") or not value.get("parent_scope"):
            errors.append("proposal kind and parent_scope are required")
        if not value.get("intended_responsibility") or not value.get("verification_responsibility"):
            errors.append("proposal responsibilities are required")
        if not _new_surface_proposal_justified(value):
            errors.append("existing-surface insufficiency justification is required")
        # A proposal must not masquerade as an already verified surface.
        if proposal_id in existing:
            errors.append("proposal ID conflicts with an existing surface")
        if errors:
            value["validation_status"] = "REJECTED"
            value["validation_errors"] = errors
            rejected.append(value)
        else:
            value["validation_status"] = "VALIDATED"
            value["provenance"] = DERIVED_PLAN_DECISION
            accepted.append(value)
    return {"validated": accepted, "rejected": rejected}


def bind_impact_decisions_to_seeds(candidate, impact_seeds, registry=None,
                                   allow_legacy_exact=False):
    """Bind semantic decisions to deterministic impact slots.

    The seed, not the model, owns the existing surface identity.  The only
    normalization performed here is the safe ``IMPACT[-_]NNN`` orchestration
    ID normalization.  A legacy injected test response may be associated by
    its already-canonical surface ID, but only under the explicit compatibility
    flag and never by fuzzy path or symbol inference.
    """
    raw = normalize_impact_map(candidate)
    seeds = [item for item in list(impact_seeds or []) if isinstance(item, dict)]
    seed_by_id = {}
    seed_by_surface = {}
    for seed in seeds:
        impact_id = normalize_impact_id(seed.get("impact_id"))
        if impact_id:
            seed_by_id[impact_id] = seed
        if seed.get("surface_id"):
            seed_by_surface.setdefault(str(seed.get("surface_id")), []).append(seed)
    bound = []
    rejected = []
    warnings = []
    unknown = 0
    seen = set()
    for item in list(raw.get("impacts", []) or [])[:MAX_IMPACT_ENTRIES]:
        value = copy.deepcopy(item)
        original_id = str(value.get("impact_id") or "").strip()
        impact_id = normalize_impact_id(original_id)
        seed = seed_by_id.get(impact_id)
        claimed_surface = str(value.get("model_surface_id") or value.get("surface_id") or "").strip()
        # Existing visible architecture tests use IMP-### IDs.  This narrow
        # compatibility path is based on an explicit canonical surface claim;
        # normal weak-model inference never receives this escape hatch.
        legacy_match = re.fullmatch(r"IMP[-_](\d+)", original_id, re.IGNORECASE)
        if (
            seed is None and allow_legacy_exact
            and legacy_match
        ):
            legacy_id = f"IMPACT-{int(legacy_match.group(1)):03d}"
            # Compatibility can translate an old IMP-### label only when the
            # same deterministic ordinal already exists.  It must not turn an
            # unknown impact label into a valid seed merely because a path or
            # surface happens to look familiar.
            if legacy_id in seed_by_id:
                candidates = []
                if registry:
                    legacy_surface = _surface_for_legacy_identity(
                        value, list(canonical_surface_by_id(registry).values()),
                        _surface_evidence_by_id([]),
                    )
                    if legacy_surface:
                        candidates = seed_by_surface.get(str(legacy_surface.get("surface_id")), [])
                if not candidates and claimed_surface:
                    candidates = seed_by_surface.get(claimed_surface, [])
                if len(candidates) == 1:
                    seed = candidates[0]
                    impact_id = normalize_impact_id(seed.get("impact_id"))
        if seed is None:
            if value.get("new_surface_proposal_ids"):
                # New-surface proposals intentionally do not need an existing
                # seed.  Their explicit proposal contract is checked later.
                value["impact_id"] = impact_id or original_id
                bound.append(value)
                continue
            rejected.append({
                "impact_id": impact_id or original_id,
                "errors": ["unknown deterministic impact seed"],
            })
            unknown += 1
            continue
        if impact_id in seen:
            rejected.append({
                "impact_id": impact_id,
                "errors": ["impact ID is duplicated after safe normalization"],
            })
            continue
        seen.add(impact_id)
        value["impact_id"] = impact_id
        value["surface_id"] = str(seed.get("surface_id") or "")
        value["seed_id"] = seed.get("seed_id")
        value["seed_surface_id"] = str(seed.get("surface_id") or "")
        if claimed_surface and claimed_surface != value["surface_id"]:
            warnings.append({
                "impact_id": impact_id,
                "field": "surface_id",
                "value": claimed_surface,
                "reason": "model surface binding ignored; deterministic seed remains authoritative",
            })
        bound.append(value)
    return {
        "candidate": {
            **raw,
            "impacts": bound,
        },
        "rejected": rejected,
        "unknown": unknown,
        "warnings": warnings,
        "seed_mode": bool(seeds),
        "received": len(_candidate_impact_items(candidate)),
        "bound": len(bound),
    }


bind_surface_bound_decisions = bind_impact_decisions_to_seeds


def hydrate_impact_map(candidate, registry, requirements, evidence,
                       allow_legacy_exact=False, impact_seeds=None):
    """Bind planner claims to canonical surfaces and drop model identity authority.

    The returned map contains only canonical existing-project identity.  Any
    inconsistent model-authored path, symbol, evidence, or interface is
    reported in ``hydration_errors`` and never survives as an actionable
    surface.
    """
    registry = registry if isinstance(registry, dict) else {}
    registry_check = validate_canonical_surface_registry(registry, evidence)
    by_id = canonical_surface_by_id(registry)
    evidence_by_id = _surface_evidence_by_id(evidence)
    seed_mode = impact_seeds is not None
    binding = bind_impact_decisions_to_seeds(
        candidate, impact_seeds if seed_mode else [], registry=registry,
        allow_legacy_exact=allow_legacy_exact,
    ) if seed_mode else {
        "candidate": normalize_impact_map(candidate), "rejected": [], "warnings": [],
        "seed_mode": False, "received": len(normalize_impact_map(candidate).get("impacts", [])),
        "bound": len(normalize_impact_map(candidate).get("impacts", [])),
    }
    raw = binding["candidate"]
    errors = list(registry_check.get("errors", [])) if not registry_check.get("valid") else []
    warnings = [
        f"{item.get('impact_id')}: {item.get('field')} optional binding ignored"
        for item in binding.get("warnings", [])
    ]
    rejected = list(binding.get("rejected", []))
    malformed_count = sum(
        1 for item in _candidate_impact_items(candidate) if not isinstance(item, dict)
    )
    rejected.extend({
        "impact_id": "<malformed>",
        "errors": ["impact decision must be an object"],
    } for _ in range(malformed_count))
    errors.extend(
        f"{item.get('impact_id')}: {error}"
        for item in rejected for error in item.get("errors", [])
    )
    proposal_result = validate_new_surface_proposals(
        raw.get("new_surface_proposals", []), requirements, registry,
    )
    proposal_by_id = {
        str(item.get("proposal_id")): item for item in proposal_result.get("validated", [])
    }
    proposal_errors = [
        f"{item.get('proposal_id')}: {error}"
        for item in proposal_result.get("rejected", [])
        for error in item.get("validation_errors", [])
    ]
    errors.extend(proposal_errors)
    rejected_count_before_impacts = len(rejected)
    hydrated = []
    req_by_id = {item["requirement_id"]: item for item in active_requirements(requirements)}
    metrics = {
        "impact_unknown_surface_references": 0,
        "impact_unknown_impact_seed_references": int(binding.get("unknown", 0) or 0),
        "impact_surface_evidence_mismatches": 0,
        "impact_invented_existing_paths_rejected": 0,
        "impact_invented_interfaces_rejected": 0,
        "impact_invalid_optional_fields_rejected": 0,
        "impact_invalid_requirement_references_rejected": 0,
        "impact_seed_surface_binding_conflicts": len(binding.get("warnings", [])),
        "impact_seed_decisions_received": binding.get("received", 0),
        "impact_seed_decisions_validated": 0,
        "impact_seed_decisions_rejected": len(binding.get("rejected", [])),
    }
    seen = set()

    def add_optional_interface(interface_id, target_surface, interface_ids, interface_names,
                                decision_errors=None):
        interface = by_id.get(str(interface_id))
        compatible = bool(interface and interface.get("kind") == "INTERFACE")
        if compatible and target_surface:
            if target_surface.get("kind") == "OWNER" and interface.get("owner_surface_id"):
                compatible = interface.get("owner_surface_id") == target_surface.get("surface_id")
            elif target_surface.get("kind") == "INTERFACE":
                compatible = (
                    interface.get("surface_id") == target_surface.get("surface_id")
                    or interface.get("owner_surface_id") == target_surface.get("owner_surface_id")
                )
            else:
                compatible = False
        if not compatible:
            metrics["impact_invented_interfaces_rejected"] += 1
            metrics["impact_invalid_optional_fields_rejected"] += 1
            if decision_errors is not None and not seed_mode:
                decision_errors.append(f"invalid interface surface reference {interface_id}")
            return
        if not surface_evidence_supports(
            interface, interface.get("evidence_ids", []), evidence,
        ):
            metrics["impact_invented_interfaces_rejected"] += 1
            metrics["impact_invalid_optional_fields_rejected"] += 1
            if decision_errors is not None and not seed_mode:
                decision_errors.append(f"unsupported interface surface reference {interface_id}")
            return
        if interface["surface_id"] not in interface_ids:
            interface_ids.append(interface["surface_id"])
            interface_names.append(str(interface.get("symbol") or ""))

    for item in list(raw.get("impacts", []) or [])[:MAX_IMPACT_ENTRIES]:
        impact_id = str(item.get("impact_id", "")).strip()
        item_errors = []
        if not impact_id or impact_id in seen:
            item_errors.append("impact ID is missing or duplicated")
        seen.add(impact_id)
        disposition = str(item.get("disposition", "")).upper().strip()
        if disposition not in DISPOSITIONS:
            item_errors.append("invalid planner disposition")
        action = _compact(item.get("action") or item.get("reason"), MAX_TEXT_CHARS)
        if not action:
            item_errors.append("impact action/reason is required")
        raw_requirement_ids = _list_value(item.get("requirement_ids"))
        requirement_ids = _bounded_ids(
            [str(value) for value in raw_requirement_ids if str(value) in req_by_id],
            MAX_REQUIREMENT_REFS_PER_IMPACT,
        )
        if len(requirement_ids) < len(set(str(value) for value in raw_requirement_ids)):
            metrics["impact_invalid_requirement_references_rejected"] += 1
            warnings.append(f"{impact_id}: unknown Source Requirement relationship removed")
        if not requirement_ids:
            item_errors.append("impact requires at least one valid Source Requirement relationship")
        proposal_ids = _bounded_ids(_list_value(item.get("new_surface_proposal_ids")), 4)
        surface_id = str(item.get("surface_id") or "").strip()
        surface = by_id.get(surface_id) if surface_id else None
        if not surface and allow_legacy_exact and not surface_id and not seed_mode:
            surface = _surface_for_legacy_identity(item, list(by_id.values()), evidence_by_id)
            if surface:
                surface_id = str(surface.get("surface_id"))
        if surface_id and proposal_ids:
            item_errors.append("impact must use either canonical surface or new-surface proposal authority")
        if not surface and not surface_id and proposal_ids:
            selected_proposals = [proposal_by_id[item_id] for item_id in proposal_ids if item_id in proposal_by_id]
            if len(selected_proposals) != len(proposal_ids):
                item_errors.append("unknown or rejected new-surface proposal reference")
            model_path = _normal_path(item.get("model_path"))
            if model_path:
                metrics["impact_invented_existing_paths_rejected"] += 1
                item_errors.append("new-surface impact cannot author an existing repository path")
            if item.get("model_symbols") or item.get("model_existing_owner"):
                metrics["impact_invented_existing_paths_rejected"] += 1
                item_errors.append("new-surface impact cannot claim verified existing identity")
            if item.get("model_repository_evidence_ids"):
                metrics["impact_surface_evidence_mismatches"] += 1
                item_errors.append("new-surface proposal cannot claim existing-surface evidence")
            interface_ids = []
            interface_names = []
            if item.get("existing_interfaces_to_reuse"):
                metrics["impact_invented_interfaces_rejected"] += 1
                metrics["impact_invalid_optional_fields_rejected"] += 1
            for interface_id in _list_value(item.get("interfaces_to_reuse")):
                add_optional_interface(interface_id, None, interface_ids, interface_names)
            proposal_requirement_ids = {
                str(requirement_id)
                for proposal in selected_proposals
                for requirement_id in proposal.get("requirement_ids", [])
            }
            if not set(requirement_ids).issubset(proposal_requirement_ids):
                item_errors.append("impact requirements are not authorized by its new-surface proposal")
            canonical = {
                "impact_id": impact_id,
                "surface_id": "",
                "canonical_surface_id": "",
                "disposition": disposition,
                "component": "; ".join(
                    str(proposal.get("intended_responsibility") or proposal.get("proposal_id"))
                    for proposal in selected_proposals
                ),
                "path": "",
                "symbols": [],
                "impact_kind": _impact_kind_for_disposition(disposition, item.get("impact_kind")),
                "requirement_ids": requirement_ids,
                "repository_evidence_ids": [],
                "reason": item.get("reason", ""),
                "existing_owner": "",
                "existing_interfaces_to_reuse": _bounded_strings(interface_names, 6, 180),
                "interfaces_to_reuse": _bounded_ids(interface_ids, 6),
                "interface_surface_ids": _bounded_ids(interface_ids, 6),
                "preserve": _bounded_strings(_list_value(item.get("preserve")), 6, 300),
                "candidate_change": action,
                "action": action,
                "local_verification": _bounded_strings(
                    _list_value(item.get("local_verification") or item.get("verification")), 6, 300,
                ),
                "verification": _bounded_strings(
                    _list_value(item.get("verification") or item.get("local_verification")), 6, 300,
                ),
                "necessity_status": item.get("necessity_status"),
                "new_surface_proposal_ids": proposal_ids,
                "surface_kind": NEW_SURFACE_PROPOSAL,
                "surface_role": "NEW_SURFACE",
                "owner_surface_id": None,
                "provenance": DERIVED_PLAN_DECISION,
            }
            if item_errors:
                rejected.append({"impact_id": impact_id, "errors": item_errors})
                errors.extend(f"{impact_id}: {error}" for error in item_errors)
            else:
                hydrated.append(canonical)
            continue
        if not surface:
            metrics["impact_unknown_surface_references"] += 1
            if item.get("model_path") or item.get("path"):
                metrics["impact_invented_existing_paths_rejected"] += 1
            item_errors.append("unknown canonical surface reference")
        if surface:
            model_path = _normal_path(item.get("model_path"))
            if model_path and model_path != _normal_path(surface.get("path")):
                metrics["impact_invented_existing_paths_rejected"] += 1
                if seed_mode:
                    warnings.append(f"{impact_id}: model path ignored; seed binding is authoritative")
                else:
                    item_errors.append("model path conflicts with canonical surface path")
            if not _surface_symbols_supported(surface, item.get("model_symbols"), evidence_by_id):
                metrics["impact_invented_existing_paths_rejected"] += 1
                if seed_mode:
                    warnings.append(f"{impact_id}: model symbol ignored; seed binding is authoritative")
                elif allow_legacy_exact and _path_symbols_supported(
                    surface.get("path"), item.get("model_symbols"), evidence_by_id,
                ):
                    pass
                else:
                    item_errors.append("model symbol conflicts with canonical surface symbol")
            model_evidence = set(str(value) for value in _list_value(item.get("model_repository_evidence_ids")))
            evidence_supported = surface_evidence_supports(surface, model_evidence, evidence)
            if model_evidence and not evidence_supported and allow_legacy_exact and not seed_mode:
                evidence_supported = all(
                    evidence_by_id.get(evidence_id)
                    and _normal_path(evidence_by_id[evidence_id].get("path"))
                    == _normal_path(surface.get("path"))
                    for evidence_id in model_evidence
                )
            if model_evidence and not evidence_supported:
                metrics["impact_surface_evidence_mismatches"] += 1
                if seed_mode:
                    warnings.append(f"{impact_id}: model evidence ignored; seed binding is authoritative")
                else:
                    item_errors.append("model evidence does not support canonical surface")
            interface_ids = []
            interface_names = []
            model_interfaces = _list_value(item.get("existing_interfaces_to_reuse"))
            if model_interfaces and not _list_value(item.get("interfaces_to_reuse")) and allow_legacy_exact:
                for name in model_interfaces:
                    matches = [
                        interface for interface in by_id.values()
                        if interface.get("kind") == "INTERFACE"
                        and str(interface.get("symbol")) == str(name)
                    ]
                    if len(matches) == 1:
                        add_optional_interface(matches[0]["surface_id"], surface, interface_ids, interface_names)
                    else:
                        metrics["impact_invented_interfaces_rejected"] += 1
                        metrics["impact_invalid_optional_fields_rejected"] += 1
                        if not seed_mode:
                            item_errors.append("legacy interface name is not canonical")
            for interface_id in _list_value(item.get("interfaces_to_reuse")):
                add_optional_interface(
                    interface_id, surface, interface_ids, interface_names, item_errors,
                )
            if model_interfaces and interface_ids and set(str(value) for value in model_interfaces) != set(interface_names):
                metrics["impact_invented_interfaces_rejected"] += 1
                metrics["impact_invalid_optional_fields_rejected"] += 1
                if not seed_mode:
                    item_errors.append("model interface names conflict with canonical interface IDs")
            canonical = {
                "impact_id": impact_id,
                "surface_id": surface["surface_id"],
                "canonical_surface_id": surface["surface_id"],
                "disposition": disposition,
                "component": str(surface.get("symbol") or surface.get("role") or surface.get("path")),
                "path": _normal_path(surface.get("path")),
                "symbols": _bounded_strings(
                    [surface.get("symbol")] if surface.get("symbol") else [], 6, 160,
                ),
                "impact_kind": _impact_kind_for_disposition(disposition, item.get("impact_kind")),
                "requirement_ids": requirement_ids,
                "repository_evidence_ids": _bounded_ids(
                    surface.get("evidence_ids"), MAX_EVIDENCE_REFS_PER_IMPACT,
                ),
                "reason": item.get("reason", ""),
                "existing_owner": str(surface.get("symbol") or ""),
                "existing_interfaces_to_reuse": _bounded_strings(interface_names, 6, 180),
                "interfaces_to_reuse": _bounded_ids(interface_ids, 6),
                "interface_surface_ids": _bounded_ids(interface_ids, 6),
                "preserve": _bounded_strings(_list_value(item.get("preserve")), 6, 300),
                "candidate_change": action,
                "action": action,
                "local_verification": _bounded_strings(
                    _list_value(item.get("local_verification") or item.get("verification")), 6, 300,
                ),
                "verification": _bounded_strings(
                    _list_value(item.get("verification") or item.get("local_verification")), 6, 300,
                ),
                "test_contract": _bounded_strings(
                    _list_value(item.get("test_contract") or item.get("verification")), 6, 300,
                ),
                "local_test_contract": _bounded_strings(
                    _list_value(item.get("local_test_contract") or item.get("verification")), 6, 300,
                ),
                "necessity_status": item.get("necessity_status"),
                "new_surface_proposal_ids": proposal_ids,
                "surface_kind": surface.get("kind"),
                "surface_role": surface.get("role"),
                "owner_surface_id": surface.get("owner_surface_id"),
                "provenance": DERIVED_PLAN_DECISION,
            }
            if item_errors:
                rejected.append({"impact_id": impact_id, "errors": item_errors})
                errors.extend(f"{impact_id}: {error}" for error in item_errors)
            else:
                hydrated.append(canonical)
        else:
            rejected.append({"impact_id": impact_id, "errors": item_errors})
            errors.extend(f"{impact_id}: {error}" for error in item_errors)

    metrics["impact_seed_decisions_validated"] = len(hydrated)
    metrics["impact_seed_decisions_rejected"] = len(rejected)
    result = {
        "version": 1,
        "task_goal": raw.get("task_goal", ""),
        "impacts": hydrated,
        "integration_verification": list(raw.get("integration_verification", []) or []),
        "insufficient_evidence": list(raw.get("insufficient_evidence", []) or []),
        "new_surface_proposals": proposal_result.get("validated", []),
        "canonical_surface_registry_version": registry.get("version"),
        "bounds": copy.deepcopy(raw.get("bounds", {})),
        "provenance": DERIVED_PLAN_DECISION,
        # Seed-bound flow tolerates rejected individual decisions and optional
        # fields as long as at least one accepted decision remains canonical.
        "hydration_valid": bool(registry_check.get("valid")) and bool(hydrated)
        and (seed_mode or not (errors or warnings)),
        "hydration_errors": (errors + warnings)[:48],
        "hydration_rejected_impacts": rejected[:MAX_IMPACT_ENTRIES],
        "impact_decisions_received": binding.get("received", 0),
        "impact_decisions_validated": len(hydrated),
        "impact_decisions_rejected": len(rejected),
        **metrics,
    }
    return result


canonicalize_impact_map = hydrate_impact_map


def audit_impact_surfaces(candidate, registry, requirements=None, evidence=None):
    """Independently classify every raw candidate surface claim.

    This is an audit view only; its labels never become planner authority.
    """
    raw = normalize_impact_map(candidate)
    by_id = canonical_surface_by_id(registry)
    evidence_by_id = _surface_evidence_by_id(evidence)
    result = []
    seen = set()
    for item in raw.get("impacts", [])[:MAX_IMPACT_ENTRIES]:
        surface_id = str(item.get("surface_id") or "")
        surface = by_id.get(surface_id)
        if not surface and item.get("model_path"):
            classification = "UNSUPPORTED_CHANGE"
            reason = "model-authored existing path is not a canonical surface"
        elif not surface:
            classification = "MISSING_REQUIRED_SURFACE"
            reason = "candidate did not bind to an existing canonical surface"
        else:
            seen.add(surface_id)
            model_evidence = set(str(value) for value in item.get("model_repository_evidence_ids", []))
            evidence_ok = not model_evidence or surface_evidence_supports(surface, model_evidence, evidence)
            disposition = item.get("disposition")
            if not evidence_ok:
                classification = "UNSUPPORTED_CHANGE"
                reason = "selected evidence does not support the canonical surface"
            elif disposition in {"MUST_CHANGE", "TEST_CHANGE"}:
                classification = "REQUIRED_CHANGE"
                reason = "bounded mutation/test disposition with canonical evidence"
            elif disposition in {"INTERFACE_REUSE", "PRESERVATION_ONLY", "VERIFY_ONLY"}:
                classification = "PRESERVATION_ONLY"
                reason = "reuse, verification, or preservation disposition"
            else:
                classification = "POSSIBLY_REQUIRED"
                reason = "candidate disposition is not a proven mutation"
        result.append({
            "impact_id": item.get("impact_id"), "surface_id": surface_id or None,
            "path": _normal_path(surface.get("path")) if surface else _normal_path(item.get("model_path")),
            "classification": classification, "reason": reason,
        })
    # A required current TEST surface is auditable as missing when the map
    # omits explicit test responsibility.
    reqs = active_requirements(requirements or [])
    has_test_requirement = any(_TEST_RE.search(item["text"]) for item in reqs)
    if has_test_requirement and not any(
        item.get("surface_id") in by_id and by_id[item.get("surface_id")].get("kind") == "TEST"
        for item in raw.get("impacts", [])
    ):
        tests = [item for item in by_id.values() if item.get("kind") == "TEST"]
        if tests:
            result.append({
                "impact_id": None, "surface_id": tests[0].get("surface_id"),
                "path": tests[0].get("path"), "classification": "MISSING_REQUIRED_SURFACE",
                "reason": "active test requirement has no explicit TEST_CHANGE responsibility",
            })
    return result


def validate_surface_binding(impact, registry, evidence=None):
    """Return the deterministic semantic binding result for one impact."""
    value = impact if isinstance(impact, dict) else {}
    surface = canonical_surface_by_id(registry).get(
        str(value.get("surface_id") or value.get("canonical_surface_id") or "")
    )
    errors = []
    if not surface:
        errors.append("unknown canonical surface")
    else:
        if _normal_path(value.get("path")) != _normal_path(surface.get("path")):
            errors.append("path does not match canonical surface")
        refs = set(str(item) for item in value.get("repository_evidence_ids", []))
        if refs != set(str(item) for item in surface.get("evidence_ids", [])):
            errors.append("evidence refs are not hydrated from canonical surface")
        elif not surface_evidence_supports(surface, refs, evidence):
            errors.append("surface/evidence relation is unsupported")
    return {"valid": not errors, "errors": errors[:8], "surface": copy.deepcopy(surface)}


def validate_planner_output_detailed(candidate, requirements=None, allow_legacy=False,
                                     impact_seeds=None):
    """Canonicalize and validate the provider-facing Stage 3 response.

    The boolean compatibility wrapper below remains the public contract used
    by older callers.  This detailed form keeps the bounded reason visible to
    the structured-call seam without moving semantic authority out of the
    existing validator/hydrator.
    """
    canonicalization = canonicalize_impact_map_candidate(candidate)
    if not canonicalization.get("valid"):
        canonicalization["validation_status"] = "FAILED"
        canonicalization["validator"] = "validate_planner_output"
        return canonicalization
    value = canonicalization.get("canonical_candidate") or {}
    impacts = value.get("impacts", [])
    errors = []
    if not isinstance(impacts, list) or not impacts:
        errors.append("at least one impact decision is required")
        result = _impact_map_result(
            IMPACT_MAP_REQUIRED_SEMANTIC_FIELD_MISSING,
            canonicalization.get("source_envelope"), value, errors,
            canonicalization=canonicalization.get("canonicalization", "APPLIED"),
        )
        result["validation_status"] = "FAILED"
        result["validator"] = "validate_planner_output"
        return result
    if len(impacts) > MAX_IMPACT_ENTRIES:
        errors.append("impact entry bound exceeded")

    req_ids = {item["requirement_id"] for item in active_requirements(requirements or [])}
    seed_ids = {
        normalize_impact_id(item.get("impact_id"))
        for item in list(impact_seeds or []) if isinstance(item, dict)
    }
    usable = 0
    fatal_semantic_error = len(impacts) > MAX_IMPACT_ENTRIES
    seen = set()
    for index, item in enumerate(impacts, 1):
        location = f"impacts[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{location} must be an object")
            continue
        impact_id = str(item.get("impact_id") or "").strip()
        if impact_id.casefold() in _IMPACT_PLACEHOLDER_IDS:
            errors.append(f"{location}.impact_id is missing or a placeholder")
            continue
        normalized_id = normalize_impact_id(impact_id)
        if normalized_id in seen:
            errors.append(f"{impact_id}: impact ID is duplicated")
            fatal_semantic_error = True
            continue
        seen.add(normalized_id)
        refs = _list_value(item.get("requirement_ids"))
        if not refs:
            errors.append(f"{impact_id}: requirement_ids is required")
            continue
        if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            errors.append(f"{impact_id}: requirement_ids must contain non-empty strings")
            continue
        disposition = str(item.get("disposition", "")).upper().strip()
        if not disposition and allow_legacy:
            disposition = _disposition_for_impact(item)
        if disposition not in DISPOSITIONS:
            errors.append(f"{impact_id}: invalid planner disposition")
            continue
        action = item.get("action") or item.get("reason") or item.get("candidate_change")
        if not isinstance(action, str) or not action.strip():
            errors.append(f"{impact_id}: action or reason is required")
            continue
        if seed_ids and not seed_ids.intersection({normalized_id}) and not _list_value(
            item.get("new_surface_proposal_ids")
        ):
            errors.append(f"{impact_id}: decision does not reference a known impact seed")
            continue
        # Unknown requirement IDs are deliberately left for per-decision
        # relationship validation, so a mixed response can still proceed.
        if req_ids and not any(str(ref).strip() for ref in refs):
            errors.append(f"{impact_id}: no usable Source Requirement relationship")
            continue
        usable += 1
    forbidden = _forbidden_context_key(value)
    if forbidden:
        errors.append(f"raw context field is forbidden: {forbidden}")
        usable = 0
        fatal_semantic_error = True
    if usable and not fatal_semantic_error:
        result = _impact_map_result(
            "VALID", canonicalization.get("source_envelope"), value, errors,
            canonicalization=canonicalization.get("canonicalization", "APPLIED"),
        )
        result["validation_status"] = "PASSED"
        result["validator"] = "validate_planner_output"
        result["usable_decisions"] = usable
        return result
    missing = any(
        "required" in error or "missing" in error or "placeholder" in error
        for error in errors
    )
    status = (
        IMPACT_MAP_REQUIRED_SEMANTIC_FIELD_MISSING
        if missing else IMPACT_MAP_SEMANTIC_VALIDATION_FAILED
    )
    result = _impact_map_result(
        status, canonicalization.get("source_envelope"), value, errors,
        canonicalization=canonicalization.get("canonicalization", "APPLIED"),
    )
    result["validation_status"] = "FAILED"
    result["validator"] = "validate_planner_output"
    result["usable_decisions"] = 0
    return result


def validate_planner_output(candidate, requirements=None, allow_legacy=False,
                            impact_seeds=None):
    """Boolean compatibility wrapper around detailed canonical validation."""
    return bool(validate_planner_output_detailed(
        candidate, requirements=requirements, allow_legacy=allow_legacy,
        impact_seeds=impact_seeds,
    ).get("valid"))


def _forbidden_context_key(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in _RAW_CONTEXT_KEYS:
                return str(key)
            found = _forbidden_context_key(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _forbidden_context_key(item)
            if found:
                return found
    return None


def validate_impact_map(impact_map, requirements, evidence, project_mode=EXISTING_PROJECT,
                        surface_registry=None):
    errors = []
    value = impact_map if isinstance(impact_map, dict) else {}
    requirement_ids = {item["requirement_id"] for item in active_requirements(requirements)}
    evidence_ids = {item["evidence_id"] for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)}
    impacts = list(value.get("impacts", []) or [])
    if not impacts:
        errors.append("at least one impact is required")
    if len(impacts) > MAX_IMPACT_ENTRIES:
        errors.append("impact entry bound exceeded")
    seen = set()
    supported = 0
    preservation = 0
    surface_by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    strict_surface_binding = bool(surface_registry)
    proposal_result = validate_new_surface_proposals(
        value.get("new_surface_proposals", []), requirements, surface_registry or {},
    ) if strict_surface_binding else {"validated": [], "rejected": []}
    proposal_by_id = {
        str(item.get("proposal_id")): item for item in proposal_result.get("validated", [])
    }
    if proposal_result.get("rejected"):
        errors.append("new-surface proposal validation failed")
    for item in impacts:
        if not isinstance(item, dict):
            errors.append("impact entry must be an object")
            continue
        impact_id = str(item.get("impact_id", ""))
        if not impact_id or impact_id in seen:
            errors.append("impact IDs must be present and unique")
        seen.add(impact_id)
        kind = str(item.get("impact_kind", ""))
        necessity = str(item.get("necessity_status", ""))
        disposition = str(item.get("disposition", ""))
        if kind not in IMPACT_KINDS:
            errors.append(f"{impact_id}: invalid impact kind")
        if necessity not in NECESSITY_STATUSES:
            errors.append(f"{impact_id}: invalid necessity status")
        req_refs = set(str(ref) for ref in item.get("requirement_ids", []))
        evidence_refs = set(str(ref) for ref in item.get("repository_evidence_ids", []))
        surface_id = str(item.get("surface_id") or item.get("canonical_surface_id") or "")
        proposal_refs = {
            str(ref) for ref in item.get("new_surface_proposal_ids", []) if ref
        }
        new_surface_binding = bool(proposal_refs) and not surface_id
        if not req_refs or not req_refs.issubset(requirement_ids):
            errors.append(f"{impact_id}: concrete impact requires valid Source Requirement IDs")
        if project_mode == EXISTING_PROJECT and (
            not new_surface_binding
            and (not evidence_refs or not evidence_refs.issubset(evidence_ids))
        ):
            errors.append(f"{impact_id}: existing-project impact requires accepted repository evidence")
        if len(req_refs) > MAX_REQUIREMENT_REFS_PER_IMPACT:
            errors.append(f"{impact_id}: requirement reference bound exceeded")
        if len(evidence_refs) > MAX_EVIDENCE_REFS_PER_IMPACT:
            errors.append(f"{impact_id}: evidence reference bound exceeded")
        if necessity == "MUST_CHANGE" and (
            not req_refs or (not evidence_refs and not new_surface_binding)
        ):
            errors.append(f"{impact_id}: unsupported MUST_CHANGE")
        if kind == "PRESERVATION_ONLY" and necessity != "PRESERVATION_ONLY":
            errors.append(f"{impact_id}: preservation-only surface cannot be MUST_CHANGE")
        if strict_surface_binding and disposition not in DISPOSITIONS:
            errors.append(f"{impact_id}: canonical disposition is required")
        if strict_surface_binding and disposition == "PRESERVATION_ONLY" and necessity != "PRESERVATION_ONLY":
            errors.append(f"{impact_id}: preservation disposition has invalid necessity")
        semantic_surface_valid = True
        if strict_surface_binding:
            surface = surface_by_id.get(surface_id)
            if surface and proposal_refs:
                errors.append(f"{impact_id}: impact has conflicting target authorities")
                semantic_surface_valid = False
            elif not surface and new_surface_binding:
                selected_proposals = [
                    proposal_by_id[item_id] for item_id in proposal_refs
                    if item_id in proposal_by_id
                ]
                if len(selected_proposals) != len(proposal_refs):
                    errors.append(f"{impact_id}: new-surface proposal binding is invalid")
                    semantic_surface_valid = False
                authorized_requirements = {
                    str(requirement_id)
                    for proposal in selected_proposals
                    for requirement_id in proposal.get("requirement_ids", [])
                }
                if not req_refs.issubset(authorized_requirements):
                    errors.append(f"{impact_id}: new-surface proposal does not authorize its requirements")
                    semantic_surface_valid = False
                if evidence_refs or _normal_path(item.get("path")):
                    errors.append(f"{impact_id}: new-surface binding cannot claim existing identity")
                    semantic_surface_valid = False
                for interface_id in item.get("interfaces_to_reuse", []) or []:
                    interface = surface_by_id.get(str(interface_id))
                    if not interface or interface.get("kind") != "INTERFACE":
                        errors.append(f"{impact_id}: interface reuse must reference an INTERFACE surface")
                        semantic_surface_valid = False
                    elif str(interface.get("symbol")) not in item.get("existing_interfaces_to_reuse", []):
                        errors.append(f"{impact_id}: hydrated interface identity is inconsistent")
                        semantic_surface_valid = False
            elif not surface:
                errors.append(f"{impact_id}: canonical surface binding is required")
                semantic_surface_valid = False
            else:
                if _normal_path(item.get("path")) != _normal_path(surface.get("path")):
                    errors.append(f"{impact_id}: path is not derived from canonical surface")
                    semantic_surface_valid = False
                expected_evidence = set(str(ref) for ref in surface.get("evidence_ids", []))
                if evidence_refs != expected_evidence:
                    errors.append(f"{impact_id}: evidence refs must be hydrated from canonical surface")
                    semantic_surface_valid = False
                elif not surface_evidence_supports(surface, evidence_refs, evidence):
                    errors.append(f"{impact_id}: surface/evidence relationship is invalid")
                    semantic_surface_valid = False
                for interface_id in item.get("interfaces_to_reuse", []) or []:
                    interface = surface_by_id.get(str(interface_id))
                    if not interface or interface.get("kind") != "INTERFACE":
                        errors.append(f"{impact_id}: interface reuse must reference an INTERFACE surface")
                        semantic_surface_valid = False
                    elif str(interface.get("symbol")) not in item.get("existing_interfaces_to_reuse", []):
                        errors.append(f"{impact_id}: hydrated interface identity is inconsistent")
                        semantic_surface_valid = False
        if req_refs and (
            project_mode != EXISTING_PROJECT or evidence_refs or new_surface_binding
        ) and semantic_surface_valid:
            supported += 1
        if necessity == "PRESERVATION_ONLY":
            preservation += 1
    forbidden = _forbidden_context_key(value)
    if forbidden:
        errors.append(f"raw context field is forbidden: {forbidden}")
    return {
        "valid": not errors,
        "errors": errors[:16],
        "impact_candidates": len(impacts),
        "impact_supported": supported,
        "impact_preservation_only": preservation,
        "serialized_chars": _json_size(value),
    }


def impact_map_is_valid(candidate, requirements=None, evidence=None, project_mode=EXISTING_PROJECT,
                        surface_registry=None):
    return validate_impact_map(
        normalize_impact_map(candidate), requirements or [], evidence or [], project_mode,
        surface_registry=surface_registry,
    )["valid"]


def _rank_requirement_ids(requirements, value, fallback_count=4):
    terms = _tokens(value)
    scored = []
    for index, item in enumerate(active_requirements(requirements)):
        overlap = len(terms & _tokens(item.get("text")))
        if overlap:
            scored.append((-overlap, index, item["requirement_id"]))
    scored.sort()
    selected = [row[2] for row in scored[:MAX_REQUIREMENT_REFS_PER_IMPACT]]
    if selected:
        return selected
    return [item["requirement_id"] for item in active_requirements(requirements)[:fallback_count]]


def _deterministic_canonical_impact_map(task_goal, requirements, evidence, registry):
    reqs = active_requirements(requirements)
    by_id = canonical_surface_by_id(registry)
    interfaces_by_path = {}
    for surface in by_id.values():
        if surface.get("kind") == "INTERFACE":
            interfaces_by_path.setdefault(_normal_path(surface.get("path")), []).append(surface)
    impacts = []
    for surface in list(registry.get("surfaces", []) or [])[:MAX_IMPACT_ENTRIES]:
        encoded = " ".join([
            str(surface.get("verified_fact", "")), str(surface.get("symbol", "")),
            str(surface.get("role", "")), str(task_goal or ""),
        ])
        requirement_ids = _rank_requirement_ids(reqs, encoded)
        role = surface.get("role")
        kind = surface.get("kind")
        preserve = [
            item["text"] for item in reqs
            if _PRESERVE_RE.search(item["text"])
            and _tokens(item["text"]) & _tokens(encoded)
        ]
        if kind == "PERSISTENCE":
            disposition = "PRESERVATION_ONLY"
        elif kind == "TEST":
            disposition = "TEST_CHANGE"
        elif kind == "INTERFACE":
            disposition = "INTERFACE_REUSE"
        elif kind == "ENTRYPOINT":
            disposition = "VERIFY_ONLY"
        elif kind == "OWNER":
            disposition = "MUST_CHANGE" if _requirement_change_required(
                requirement_ids, {item["requirement_id"]: item for item in reqs},
            ) else "VERIFY_ONLY"
        else:
            disposition = "VERIFY_ONLY"
        related_interfaces = [
            item for item in interfaces_by_path.get(_normal_path(surface.get("path")), [])
            if surface.get("kind") == "OWNER"
            and _surface_symbol_base(item.get("symbol")) == _surface_symbol_base(surface.get("symbol"))
        ]
        interface_ids = [item["surface_id"] for item in related_interfaces]
        interface_names = [str(item.get("symbol") or "") for item in related_interfaces]
        action = {
            "MUST_CHANGE": "Implement the linked behavior through the verified current owner.",
            "TEST_CHANGE": "Update or add focused coverage at the verified test boundary.",
            "INTERFACE_REUSE": "Reuse the verified current interface without creating a duplicate.",
            "PRESERVATION_ONLY": "No mutation planned; preserve the verified current behavior.",
            "VERIFY_ONLY": "Verify the linked responsibility without mutating this surface.",
        }.get(disposition, "Insufficient evidence for a mutation claim.")
        necessity = {
            "MUST_CHANGE": "MUST_CHANGE", "PRESERVATION_ONLY": "PRESERVATION_ONLY",
            "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE",
        }.get(disposition, "CANDIDATE")
        impacts.append({
            "impact_id": f"IMP-{len(impacts) + 1:03d}",
            "surface_id": surface.get("surface_id"),
            "disposition": disposition,
            "requirement_ids": requirement_ids[:MAX_REQUIREMENT_REFS_PER_IMPACT],
            "repository_evidence_ids": list(surface.get("evidence_ids", [])),
            "interfaces_to_reuse": interface_ids[:6],
            "action": action,
            "verification": [item["text"] for item in reqs[:4]],
            "preserve": _bounded_strings(preserve, 6, 300),
            "reason": surface.get("verified_fact", ""),
            "necessity_status": necessity,
            "candidate_change": action,
            "local_verification": [item["text"] for item in reqs[:4]],
            "existing_interfaces_to_reuse": interface_names[:6],
        })
    return _canonicalize_deterministic_map(
        {
            "task_goal": task_goal,
            "impacts": impacts,
            "integration_verification": [item["text"] for item in reqs[:8]],
            "insufficient_evidence": [],
        }, registry, requirements, evidence,
    )


def _canonicalize_deterministic_map(candidate, registry, requirements, evidence):
    """Canonicalize trusted deterministic seeds without a model round."""
    raw = normalize_impact_map(candidate)
    by_id = canonical_surface_by_id(registry)
    canonical_impacts = []
    for item in raw.get("impacts", []):
        surface = by_id.get(str(item.get("surface_id")))
        if not surface:
            continue
        canonical_impacts.append({
            "impact_id": item.get("impact_id"),
            "surface_id": surface.get("surface_id"),
            "canonical_surface_id": surface.get("surface_id"),
            "disposition": item.get("disposition"),
            "component": surface.get("symbol") or surface.get("role") or surface.get("path"),
            "path": _normal_path(surface.get("path")),
            "symbols": _bounded_strings([surface.get("symbol")] if surface.get("symbol") else [], 6, 160),
            "impact_kind": _impact_kind_for_disposition(item.get("disposition"), item.get("impact_kind")),
            "requirement_ids": _bounded_ids(item.get("requirement_ids"), MAX_REQUIREMENT_REFS_PER_IMPACT),
            "repository_evidence_ids": _bounded_ids(surface.get("evidence_ids"), MAX_EVIDENCE_REFS_PER_IMPACT),
            "reason": item.get("reason", ""),
            "existing_owner": surface.get("symbol", ""),
            "existing_interfaces_to_reuse": _bounded_strings(item.get("existing_interfaces_to_reuse"), 6, 180),
            "interfaces_to_reuse": _bounded_ids(item.get("interfaces_to_reuse"), 6),
            "interface_surface_ids": _bounded_ids(item.get("interfaces_to_reuse"), 6),
            "preserve": _bounded_strings(item.get("preserve"), 6, 300),
            "candidate_change": item.get("candidate_change", ""),
            "action": item.get("action", ""),
            "local_verification": _bounded_strings(item.get("local_verification"), 6, 300),
            "verification": _bounded_strings(item.get("verification"), 6, 300),
            "necessity_status": item.get("necessity_status"),
            "surface_kind": surface.get("kind"), "surface_role": surface.get("role"),
            "owner_surface_id": surface.get("owner_surface_id"),
            "provenance": DERIVED_PLAN_DECISION,
        })
    return {
        "version": 1, "task_goal": _compact(raw.get("task_goal"), 1000),
        "impacts": canonical_impacts,
        "integration_verification": _bounded_strings(raw.get("integration_verification"), 10, 320),
        "insufficient_evidence": _bounded_strings(raw.get("insufficient_evidence"), 6, 320),
        "new_surface_proposals": [],
        "canonical_surface_registry_version": registry.get("version"),
        "bounds": copy.deepcopy(raw.get("bounds", {})),
        "provenance": DERIVED_PLAN_DECISION,
    }


def deterministic_impact_map(task_goal, requirements, evidence, registry=None):
    """Source/evidence-only fallback when the bounded planner output is invalid."""
    if registry:
        return _deterministic_canonical_impact_map(task_goal, requirements, evidence, registry)
    facts = bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    reqs = active_requirements(requirements)
    preserve_requirements = [item for item in reqs if _PRESERVE_RE.search(item["text"])]
    grouped = {}
    for item in facts:
        path = item.get("path") or f"evidence:{item.get('evidence_id')}"
        grouped.setdefault(path, []).append(item)
    impacts = []
    for path, records in list(grouped.items())[:MAX_IMPACT_ENTRIES]:
        categories = {item.get("category") for item in records}
        encoded = " ".join(
            str(item.get(key, "")) for item in records for key in ("fact", "path", "symbol")
        )
        requirement_ids = _rank_requirement_ids(reqs, encoded + " " + str(task_goal))
        relevant_requirements = [
            item for item in reqs if item["requirement_id"] in set(requirement_ids)
        ]
        is_preservation = (
            "CURRENT_PERSISTENCE" in categories
            and any(_tokens(item["text"]) & _tokens(encoded) for item in preserve_requirements)
        )
        if "CURRENT_TEST" in categories:
            kind = "TEST_CHANGE"
        elif is_preservation:
            kind = "PRESERVATION_ONLY"
        elif categories & {"CURRENT_OWNER", "CURRENT_STATE_OWNER", "CURRENT_BEHAVIOR"}:
            kind = "BEHAVIOR_CHANGE"
        elif "CURRENT_INTERFACE" in categories:
            kind = "INTERFACE_REUSE"
        else:
            kind = "INTEGRATION_CHANGE"
        symbols = _bounded_strings([item.get("symbol") for item in records], 6, 160)
        component = next((symbol.split(".", 1)[0] for symbol in symbols if symbol), path)
        interfaces = _bounded_strings([
            item.get("symbol") for item in records if item.get("category") == "CURRENT_INTERFACE"
        ], 6, 180)
        preserve = _bounded_strings([
            item["text"] for item in relevant_requirements if _PRESERVE_RE.search(item["text"])
        ], 6, 300)
        if kind == "PRESERVATION_ONLY":
            candidate_change = "No mutation planned; preserve the verified current behavior."
            necessity = "PRESERVATION_ONLY"
        elif kind == "INTERFACE_REUSE":
            candidate_change = "Reuse the verified current interface for the linked requirement."
            necessity = "CANDIDATE"
        elif kind == "TEST_CHANGE":
            candidate_change = "Update or add focused coverage at the verified test boundary."
            necessity = "CANDIDATE"
        else:
            candidate_change = "Implement the linked requirement through the verified current owner."
            necessity = "CANDIDATE"
        impacts.append({
            "impact_id": f"IMP-{len(impacts) + 1:03d}",
            "component": component,
            "path": path if not path.startswith("evidence:") else "",
            "symbols": symbols,
            "impact_kind": kind,
            "requirement_ids": requirement_ids[:MAX_REQUIREMENT_REFS_PER_IMPACT],
            "repository_evidence_ids": _bounded_ids(
                [item.get("evidence_id") for item in records], MAX_EVIDENCE_REFS_PER_IMPACT,
            ),
            "reason": _compact(" ".join(item.get("fact", "") for item in records), MAX_TEXT_CHARS),
            "existing_owner": component if categories & {"CURRENT_OWNER", "CURRENT_STATE_OWNER"} else "",
            "existing_interfaces_to_reuse": interfaces,
            "preserve": preserve,
            "candidate_change": candidate_change,
            "local_verification": _bounded_strings(
                [item["text"] for item in relevant_requirements], 4, 300,
            ),
            "necessity_status": necessity,
        })
    return normalize_impact_map({
        "task_goal": task_goal,
        "impacts": impacts,
        "integration_verification": [item["text"] for item in reqs[:8]],
        "insufficient_evidence": [] if impacts else ["No accepted repository surface supports an impact claim."],
    })


def challenge_schema():
    challenge = {
        "type": "object",
        "properties": {
            "challenge_id": {"type": "string"},
            "challenge_type": {"type": "string", "enum": list(CHALLENGE_TYPES)},
            "impact_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            "surface_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "requirement_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "repository_evidence_ids": {
                "type": "array", "items": {"type": "string"}, "maxItems": 6,
            },
            "claim": {"type": "string"},
            "proposed_resolution": {"type": "string"},
            "blocking": {"type": "boolean"},
        },
        "required": [
            "challenge_id", "challenge_type", "impact_ids", "requirement_ids",
            "repository_evidence_ids", "claim", "proposed_resolution", "blocking",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "challenges": {
                "type": "array", "items": challenge, "maxItems": MAX_CHALLENGES,
            },
        },
        "required": ["challenges"],
        "additionalProperties": False,
    }


def normalize_challenges(candidate, source="MODEL"):
    candidate = candidate if isinstance(candidate, dict) else {}
    result = []
    for index, item in enumerate(list(candidate.get("challenges", []) or [])[:MAX_CHALLENGES], 1):
        if not isinstance(item, dict):
            continue
        challenge_type = str(item.get("challenge_type", "")).upper()
        if challenge_type not in CHALLENGE_TYPES:
            continue
        result.append({
            "challenge_id": _compact(item.get("challenge_id") or f"CH-{index:03d}", 80),
            "challenge_type": challenge_type,
            "impact_ids": _bounded_ids(item.get("impact_ids"), 4),
            "surface_ids": _bounded_ids(item.get("surface_ids"), 6),
            "requirement_ids": _bounded_ids(item.get("requirement_ids"), 6),
            "repository_evidence_ids": _bounded_ids(item.get("repository_evidence_ids"), 6),
            "claim": _compact(item.get("claim"), MAX_TEXT_CHARS),
            "proposed_resolution": _compact(item.get("proposed_resolution"), MAX_TEXT_CHARS),
            "blocking": bool(item.get("blocking", challenge_type in BLOCKING_CHALLENGE_TYPES)),
            "source": source,
            "provenance": DERIVED_PLAN_DECISION,
        })
    return result


def _review_impact_packet(impact):
    """Compact one canonical impact without allowing identity expansion."""
    if not isinstance(impact, dict):
        return None
    return {
        key: copy.deepcopy(impact.get(key)) for key in (
            "impact_id", "surface_id", "canonical_surface_id", "disposition",
            "impact_kind", "necessity_status", "requirement_ids",
            "repository_evidence_ids", "action", "reason", "interfaces_to_reuse",
            "existing_interfaces_to_reuse", "preserve", "verification",
            "surface_kind", "surface_role", "owner_surface_id",
        ) if impact.get(key) not in (None, "", [], {})
    }


def _review_surface_packet(surface):
    return _planner_surface_packet(surface) if isinstance(surface, dict) else None


def challenger_review_projection_hash(projection):
    """Hash a Challenger review projection without the derived hash field."""
    value = copy.deepcopy(projection if isinstance(projection, dict) else {})
    value.pop("projection_hash", None)
    return _impact_decision_hash(value)


challenger_review_projection_artifact_hash = challenger_review_projection_hash


def challenger_review_source_map_hash(impact_map):
    """Return a deterministic identity for the complete compiled Impact Map."""
    return _impact_decision_hash(copy.deepcopy(impact_map if isinstance(impact_map, dict) else {}))


def _challenger_review_projection_enabled(impact_map, role="ImpactChallenger"):
    """Opt into V24.4.4 only for an explicit V24.4 choice artifact."""
    if str(role or "").casefold() != "impactchallenger":
        return False
    value = impact_map if isinstance(impact_map, dict) else {}
    ledger = value.get("requirement_obligation_ledger")
    frame_coverage = value.get("impact_decision_frame_coverage")
    choice_coverage = value.get("impact_decision_choice_coverage")
    has_ledger = isinstance(ledger, dict) and ledger.get("version") == 2
    has_frame = bool(value.get("impact_decision_frame_hash")) or (
        isinstance(frame_coverage, dict)
        and frame_coverage.get("artifact_type") == "ImpactDecisionFrameCoverage"
    )
    has_choice = bool(value.get("impact_decision_choice_hash")) or (
        isinstance(choice_coverage, dict)
        and choice_coverage.get("artifact_type") == "ImpactDecisionChoiceCoverage"
    )
    return bool(has_ledger and has_frame and has_choice)


def _challenger_review_relative_path(path):
    return _projection_relative_path(path) if path not in (None, "") else ""


def _challenger_review_owner(owner):
    if not isinstance(owner, dict):
        return None
    value = {
        "surface_id": owner.get("surface_id"),
        "path": _challenger_review_relative_path(owner.get("path")),
        "symbol": _compact(owner.get("symbol"), 160),
    }
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def _challenger_review_contract_records(values, limit=8):
    """Compact preservation/verification contracts without file hashes."""
    result = []
    for item in list(values or [])[:limit]:
        if isinstance(item, dict):
            value = {
                "obligation_id": item.get("obligation_id"),
                "requirement_ids": _bounded_ids(item.get("requirement_ids"), 8),
                "text": _compact(item.get("text") or item.get("meaning"), 260),
                "evidence_refs": _bounded_ids(
                    item.get("evidence_refs") or item.get("evidence_ids"), 8,
                ),
                "structured_relations": _bounded_ids(item.get("structured_relations"), 8),
            }
        else:
            value = {"text": _compact(item, 260)}
        value = {key: item for key, item in value.items() if item not in (None, "", [], {})}
        if value and value not in result:
            result.append(value)
    return result


def _challenger_review_text_values(values, count=6, chars=220):
    result = []
    for item in list(values or [])[:count]:
        if isinstance(item, dict):
            item = item.get("text") or item.get("meaning") or item.get("fact")
        text = _compact(item, chars)
        if text and text not in result:
            result.append(text)
    return result


def _challenger_review_impact_classification(impact):
    """Classify a compiled impact by review responsibility, not by path."""
    value = impact if isinstance(impact, dict) else {}
    kind = str(value.get("impact_kind") or "").upper()
    surface_kind = str(value.get("surface_kind") or "").upper()
    surface_role = str(value.get("surface_role") or "").upper()
    decision = str(value.get("chosen_decision") or value.get("disposition") or "").upper()
    capabilities = value.get("decision_capabilities")
    if isinstance(capabilities, dict):
        capabilities = capabilities.get(decision, [])
    capabilities = [str(item) for item in list(capabilities or [])]
    if not capabilities and decision:
        capabilities = list(_decision_capabilities(decision))
    if kind == "BEHAVIOR_CHANGE" and (
        "IMPLEMENTATION_CHANGE" in capabilities
        or decision in {"MUST_CHANGE", "AUTHORITY_CHANGE"}
    ):
        return CHALLENGER_REVIEW_PRIMARY
    if kind == "TEST_CHANGE" or surface_kind == "TEST" or surface_role == "CURRENT_TEST":
        return EVIDENCE_ONLY
    contribution = [
        str(item).upper() for item in list(value.get("coverage_contribution", []) or [])
    ]
    if isinstance(value.get("coverage_contribution"), str):
        contribution = [str(value.get("coverage_contribution")).upper()]
    if (
        decision in {"INTERFACE_REUSE", "PRESERVATION_ONLY", "INSPECT_ONLY", "VERIFY_ONLY"}
        or contribution and all(item.startswith("INHERITED") or item in {
            "REUSE_ONLY", "INSPECTION_ONLY", "PRESERVATION_ONLY",
        } for item in contribution)
    ):
        return DETERMINISTIC_FIXED_CONTEXT
    return CHALLENGER_REVIEW_SUPPORT


def _challenger_review_impact_card(impact, classification):
    """Serialize one review card while keeping the full record out of prompt."""
    value = impact if isinstance(impact, dict) else {}
    decision = str(value.get("chosen_decision") or value.get("disposition") or "")
    capabilities = value.get("decision_capabilities")
    if isinstance(capabilities, dict):
        capabilities = capabilities.get(decision, [])
    if not capabilities:
        capabilities = _decision_capabilities(decision)
    owner = _challenger_review_owner(value.get("current_owner"))
    common = {
        "impact_id": value.get("impact_id"),
        "surface_id": value.get("surface_id") or value.get("canonical_surface_id"),
        "decision_slot_id": value.get("decision_slot_id"),
        "surface_role": value.get("surface_role"),
        "path": _challenger_review_relative_path(value.get("path")),
        "symbol": _compact(
            (value.get("symbols") or [value.get("component") or value.get("existing_owner")])[0]
            if isinstance(value.get("symbols") or [], (list, tuple))
            else value.get("component") or value.get("existing_owner"),
            160,
        ),
        "classification": classification,
        "impact_kind": value.get("impact_kind"),
        "disposition": value.get("disposition"),
        "chosen_decision": decision,
        "decision_capabilities": [str(item) for item in list(capabilities or [])],
        "requirement_ids": _bounded_ids(value.get("requirement_ids"), MAX_REQUIREMENT_REFS_PER_IMPACT),
        "obligation_ids": _bounded_ids(value.get("obligation_ids"), 12),
        "repository_evidence_ids": _bounded_ids(
            value.get("repository_evidence_ids"), MAX_EVIDENCE_REFS_PER_IMPACT,
        ),
    }
    if classification == CHALLENGER_REVIEW_PRIMARY:
        constraints = []
        for field in ("dnt", "prohibitions"):
            for text in _challenger_review_text_values(value.get(field), 8, 240):
                if text and text not in constraints:
                    constraints.append(text)
        preservation = _challenger_review_contract_records(
            value.get("required_preservation_promises")
            or value.get("preservation_promises")
        )
        verification = _challenger_review_contract_records(
            value.get("required_verification_contracts")
            or value.get("verification_contracts")
            or value.get("verification")
            or value.get("local_verification")
        )
        for text in _challenger_review_text_values(value.get("preserve"), 3, 220):
            if not any(item.get("text") == text for item in preservation):
                preservation.append({"text": text})
        common.update({
            "surface_kind": value.get("surface_kind"),
            "necessity_status": value.get("necessity_status"),
            "current_owner": owner,
            "owner_surface_id": value.get("owner_surface_id"),
            "required_interfaces": _bounded_ids(value.get("required_interfaces"), 8),
            "interfaces_to_reuse": _bounded_ids(value.get("interfaces_to_reuse"), 8),
            "interface_surface_ids": _bounded_ids(value.get("interface_surface_ids"), 8),
            "existing_interfaces_to_reuse": _bounded_strings(
                value.get("existing_interfaces_to_reuse"), 8, 200,
            ),
            "coverage_contribution": [
                str(item) for item in list(value.get("coverage_contribution", []) or [])
            ] if isinstance(value.get("coverage_contribution"), (list, tuple)) else (
                [str(value.get("coverage_contribution"))]
                if value.get("coverage_contribution") else []
            ),
            "action": _compact(value.get("action") or value.get("candidate_change"), 360),
            "reason": _compact(value.get("reason"), 360),
            "constraints": constraints[:8],
            "preservation": preservation[:8],
            "verification": verification[:8],
        })
    elif classification == DETERMINISTIC_FIXED_CONTEXT:
        contribution = value.get("coverage_contribution")
        common.update({
            "coverage_contribution": [str(item) for item in list(contribution or [])]
            if isinstance(contribution, (list, tuple)) else ([str(contribution)] if contribution else []),
            "owner_surface_id": value.get("owner_surface_id"),
            "interfaces_to_reuse": _bounded_ids(value.get("interfaces_to_reuse"), 4),
        })
    else:
        verification = _challenger_review_text_values(
            value.get("verification") or value.get("local_verification") or value.get("test_contract"),
            3, 180,
        )
        common.update({"verification": verification})
        for key in (
            "owner_surface_id", "interfaces_to_reuse",
        ):
            common.pop(key, None)
    card = common
    return {key: item for key, item in card.items() if item not in (None, "", [], {})}


def _challenger_review_model_impact_card(impact, classification):
    """Build the compact model-facing form of a compiled impact.

    The rich card remains in the immutable projection artifact.  The model
    only needs the identifiers and review facts that make a challenge
    meaningful; the full compiled record is retained in ``full_provenance``.
    """
    rich = _challenger_review_impact_card(impact, classification)
    common_keys = (
        "impact_id", "surface_id", "decision_slot_id", "surface_role", "path",
        "classification", "impact_kind", "chosen_decision", "decision_capabilities",
        "requirement_ids", "obligation_ids",
    )
    card = {key: copy.deepcopy(rich.get(key)) for key in common_keys if rich.get(key) not in (None, "", [], {})}
    if classification != CHALLENGER_REVIEW_PRIMARY:
        # The requirement and obligation ledgers carry the repeated
        # requirement mapping; the impact card carries the decision/surface
        # identity and its obligation IDs.
        card.pop("requirement_ids", None)
        card.pop("impact_kind", None)
    if classification == CHALLENGER_REVIEW_PRIMARY:
        for key in (
            "surface_kind", "necessity_status", "current_owner", "owner_surface_id",
            "coverage_contribution", "reason", "constraints", "preservation", "verification",
            "repository_evidence_ids",
        ):
            if rich.get(key) not in (None, "", [], {}):
                value = copy.deepcopy(rich.get(key))
                if key in {"reason"}:
                    value = _compact(value, 220)
                elif key in {"constraints"}:
                    # Fixed constraints are fanned in once below; keep only a
                    # short local indication on the primary card.
                    value = _challenger_review_text_values(value, 2, 120)
                elif key == "preservation":
                    value = [
                        {
                            field: copy.deepcopy(record.get(field))
                            for field in ("obligation_id", "evidence_refs")
                            if record.get(field) not in (None, "", [], {})
                        }
                        for record in _challenger_review_contract_records(value, 4)
                        if isinstance(record, dict)
                    ]
                    value = [item for item in value if item]
                elif key == "verification":
                    value = [
                        {
                            field: copy.deepcopy(record.get(field))
                            for field in ("obligation_id", "evidence_refs")
                            if record.get(field) not in (None, "", [], {})
                        }
                        for record in _challenger_review_contract_records(value, 3)
                        if isinstance(record, dict)
                    ]
                    value = [item for item in value if item]
                card[key] = value
        card.pop("constraints", None)
        card.pop("owner_surface_id", None)
    elif classification == DETERMINISTIC_FIXED_CONTEXT:
        for key in ("owner_surface_id", "interfaces_to_reuse"):
            if rich.get(key) not in (None, "", [], {}):
                card[key] = copy.deepcopy(rich.get(key))
    elif classification == EVIDENCE_ONLY:
        # Keep tests/evidence as explicit review support.  Their detailed
        # verification facts are represented once in verification_support and
        # repository_evidence rather than repeated on every test card.
        if rich.get("repository_evidence_ids") not in (None, "", [], {}):
            card["repository_evidence_ids"] = copy.deepcopy(rich["repository_evidence_ids"])
        card["review_support"] = "TEST_EVIDENCE"
    return {key: item for key, item in card.items() if item not in (None, "", [], {})}


def _challenger_review_surface_cards(impact_map, surface_registry=None):
    value = impact_map if isinstance(impact_map, dict) else {}
    registry = surface_registry if isinstance(surface_registry, dict) else {}
    by_id = canonical_surface_by_id(registry)
    result = []
    seen = set()
    for impact in list(value.get("impacts", []) or []):
        if not isinstance(impact, dict):
            continue
        surface_id = str(impact.get("surface_id") or impact.get("canonical_surface_id") or "")
        if not surface_id or surface_id in seen:
            continue
        source = by_id.get(surface_id, impact)
        seen.add(surface_id)
        card = {
            "surface_id": surface_id,
            "kind": source.get("kind") or impact.get("surface_kind"),
            "role": source.get("role") or impact.get("surface_role"),
            "path": _challenger_review_relative_path(source.get("path") or impact.get("path")),
            "symbol": _compact(source.get("symbol") or impact.get("component"), 160),
            "verified_fact": _compact(
                source.get("verified_fact") or source.get("fact") or impact.get("reason"), 260,
            ),
            "evidence_ids": _bounded_ids(
                source.get("evidence_ids") or impact.get("repository_evidence_ids"),
                MAX_SURFACE_EVIDENCE_IDS,
            ),
            "owner_surface_id": source.get("owner_surface_id") or impact.get("owner_surface_id"),
        }
        result.append({key: item for key, item in card.items() if item not in (None, "", [], {})})
    return result


def _challenger_review_model_surface_cards(surface_cards):
    """Reduce surface records to model-facing review facts and IDs."""
    result = []
    for source in list(surface_cards or []):
        if not isinstance(source, dict):
            continue
        card = {
            key: copy.deepcopy(source.get(key)) for key in (
                "surface_id", "kind", "role", "path",
            ) if source.get(key) not in (None, "", [], {})
        }
        result.append(card)
    return result


def _challenger_review_evidence_cards(impact_map, evidence):
    value = impact_map if isinstance(impact_map, dict) else {}
    referenced = {
        str(item)
        for impact in list(value.get("impacts", []) or [])
        if isinstance(impact, dict)
        for item in list(impact.get("repository_evidence_ids", []) or [])
        if item
    }
    result = []
    for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2):
        evidence_id = str(item.get("evidence_id") or "")
        if referenced and evidence_id not in referenced:
            continue
        card = {
            "evidence_id": evidence_id,
            "category": item.get("category"),
            "path": _challenger_review_relative_path(item.get("path")),
            "symbol": _compact(item.get("symbol"), 160),
            "fact": _compact(_planner_record_text(item), 180),
            "structured_relations": _bounded_ids(item.get("structured_relations"), 8),
        }
        result.append({key: value for key, value in card.items() if value not in (None, "", [], {})})
    return result


def _challenger_review_model_evidence_cards(evidence_cards):
    """Reduce repository evidence to one bounded fact per evidence ID."""
    result = []
    for source in list(evidence_cards or []):
        if not isinstance(source, dict):
            continue
        card = {
            key: copy.deepcopy(source.get(key)) for key in (
                "evidence_id", "category", "path",
            ) if source.get(key) not in (None, "", [], {})
        }
        if source.get("category") == "CURRENT_TEST":
            # Test impacts remain explicit in candidate_impact_map and their
            # IDs remain in verification_support.  Repeating every test fact
            # here would consume the same prompt budget twice.
            continue
        raw_relations = [str(item) for item in list(source.get("structured_relations", []) or []) if item]
        preferred = [
            item for item in raw_relations
            if any(token in item.upper() for token in ("USER_FACING", "PRESERVE", "STATE_OWNER"))
        ]
        relations = _bounded_ids(preferred or raw_relations, 1)
        if relations:
            card["structured_relations"] = relations
        if source.get("fact") not in (None, "", [], {}):
            card["fact"] = _compact(source.get("fact"), 125)
        result.append(card)
    return result


def _challenger_review_obligation_cards(impact_map, requirements=None):
    value = impact_map if isinstance(impact_map, dict) else {}
    frame_coverage = value.get("impact_decision_frame_coverage")
    choice_coverage = value.get("impact_decision_choice_coverage")
    frame_records = (
        list(frame_coverage.get("obligations", []) or [])
        if isinstance(frame_coverage, dict) else []
    )
    choice_records = (
        list(choice_coverage.get("obligations", []) or [])
        if isinstance(choice_coverage, dict) else []
    )
    choice_by_id = {
        str(item.get("obligation_id")): item for item in choice_records
        if isinstance(item, dict) and item.get("obligation_id")
    }
    if not frame_records:
        frame_records = _atomic_obligation_records(value.get("requirement_obligation_ledger", {}))
    impact_by_obligation = {}
    for impact in list(value.get("impacts", []) or []):
        if not isinstance(impact, dict):
            continue
        for obligation_id in list(impact.get("obligation_ids", []) or []):
            impact_by_obligation.setdefault(str(obligation_id), []).append(
                str(impact.get("impact_id"))
            )
    result = []
    for item in frame_records:
        if not isinstance(item, dict) or not item.get("obligation_id"):
            continue
        obligation_id = str(item.get("obligation_id"))
        choice = choice_by_id.get(obligation_id, {})
        covered_by = []
        for assignment in list(choice.get("covered_by", []) or []):
            if not isinstance(assignment, dict):
                continue
            covered_by.append({
                key: assignment.get(key) for key in (
                    "slot_id", "surface_id", "decision", "decision_capabilities",
                ) if assignment.get(key) not in (None, "", [], {})
            })
        assignment = choice.get("assignment") if isinstance(choice.get("assignment"), dict) else None
        if assignment:
            covered_by.append({
                "slot_id": assignment.get("slot_id"),
                "surface_id": assignment.get("surface_id"),
                "decision": assignment.get("decision") or assignment.get("chosen_decision"),
                "decision_capabilities": assignment.get("decision_capability")
                or assignment.get("decision_capabilities"),
            })
        deduplicated_covered_by = []
        seen_assignments = set()
        for covered in covered_by:
            covered = {
                key: item for key, item in covered.items()
                if item not in (None, "", [], {})
            }
            identity = _compact_json(covered)
            if identity not in seen_assignments:
                seen_assignments.add(identity)
                deduplicated_covered_by.append(covered)
        value_out = {
            "obligation_id": obligation_id,
            "requirement_id": item.get("requirement_id"),
            "obligation_type": item.get("obligation_type"),
            "meaning": _compact(item.get("meaning") or item.get("text"), 300),
            "coverage_state": "COVERED" if item.get("coverage_ready") else "UNCOVERED",
            "inherited_satisfaction": bool(item.get("inherited_satisfaction")),
            "candidate_slot_ids": _bounded_ids(
                item.get("candidate_slots") or item.get("candidate_surface_ids"), 12,
            ),
            "candidate_decision_kinds": _bounded_ids(item.get("candidate_decisions"), 8),
            "inherited_slot_ids": _bounded_ids(item.get("inherited_slots"), 12),
            "assigned_impact_ids": _bounded_ids(impact_by_obligation.get(obligation_id), 12),
            "covered_by": deduplicated_covered_by[:8],
            "evidence_refs": _bounded_ids(item.get("evidence_refs"), MAX_EVIDENCE_REFS_PER_IMPACT),
            "structured_relations": _bounded_ids(item.get("structured_relations"), 8),
        }
        result.append({key: value for key, value in value_out.items() if value not in (None, "", [], {})})
    if not result:
        # A malformed/legacy input is not silently upgraded into a V24.4
        # obligation-aware packet.  The caller's explicit mode gate controls
        # whether this artifact is used at all.
        for requirement in active_requirements(requirements):
            result.append({
                "requirement_id": requirement.get("requirement_id"),
                "meaning": _compact(requirement.get("text"), 300),
                "coverage_state": "UNKNOWN",
            })
    return result


def _challenger_review_model_obligation_cards(obligations):
    """Keep obligation identity, meaning, and assignment evidence for review."""
    result = []
    for source in list(obligations or []):
        if not isinstance(source, dict):
            continue
        card = {
            key: copy.deepcopy(source.get(key)) for key in (
                "obligation_id", "requirement_id", "obligation_type", "coverage_state",
                "inherited_satisfaction", "candidate_slot_ids", "candidate_decision_kinds",
                "inherited_slot_ids", "assigned_impact_ids",
            ) if source.get(key) not in (None, "", [], {})
        }
        if source.get("obligation_type") != "BEHAVIOR_CHANGE":
            card.pop("assigned_impact_ids", None)
        if source.get("meaning") not in (None, "", [], {}):
            card["meaning"] = _compact(source.get("meaning"), 160)
        covered_by = []
        for assignment in list(source.get("covered_by", []) or [])[:6]:
            if not isinstance(assignment, dict):
                continue
            value = {
                key: copy.deepcopy(assignment.get(key)) for key in (
                    "slot_id", "surface_id", "decision", "decision_capabilities",
                ) if assignment.get(key) not in (None, "", [], {})
            }
            if value:
                covered_by.append(value)
        if covered_by and source.get("obligation_type") == "BEHAVIOR_CHANGE":
            card["covered_by"] = covered_by
        result.append({key: item for key, item in card.items() if item not in (None, "", [], {})})
    return result


def _challenger_review_constraint_records(impact_map, obligations, task_brain=None,
                                          verified_planning_context=None, requirements=None):
    value = impact_map if isinstance(impact_map, dict) else {}
    grouped = {}
    requirement_texts = {
        _core_normalize_text(item.get("text"))
        for item in active_requirements(requirements)
        if isinstance(item, dict) and item.get("text")
    }

    def add(text, constraint_type, impact_id=None, surface_id=None, source="COMPILED_IMPACT"):
        text = _compact(text, 280)
        if not text:
            return
        if _core_normalize_text(text) in requirement_texts:
            return
        key = _core_normalize_text(text)
        entry = grouped.setdefault(key, {
            "text": text, "constraint_types": [], "impact_ids": [],
            "surface_ids": [], "source": source,
        })
        if constraint_type not in entry["constraint_types"]:
            entry["constraint_types"].append(constraint_type)
        if impact_id and str(impact_id) not in entry["impact_ids"]:
            entry["impact_ids"].append(str(impact_id))
        if surface_id and str(surface_id) not in entry["surface_ids"]:
            entry["surface_ids"].append(str(surface_id))

    for impact in list(value.get("impacts", []) or []):
        if not isinstance(impact, dict):
            continue
        impact_id = impact.get("impact_id")
        surface_id = impact.get("surface_id") or impact.get("canonical_surface_id")
        for text in list(impact.get("dnt", []) or []):
            add(text, "DNT", impact_id, surface_id)
        for text in list(impact.get("prohibitions", []) or []):
            add(text, "PROHIBITION", impact_id, surface_id)
    source = (
        verified_planning_context if isinstance(verified_planning_context, dict)
        else task_brain if isinstance(task_brain, dict) else {}
    )
    for field, constraint_type in (("dnt", "DNT"), ("prohibitions", "PROHIBITION"),
                                   ("preservation_constraints", "PRESERVATION")):
        for item in list(source.get(field, []) or []):
            add(item.get("text") if isinstance(item, dict) else item, constraint_type, source="PLANNING_CONTEXT")
    result = []
    for index, item in enumerate(sorted(grouped.values(), key=lambda entry: (
        _core_normalize_text(entry.get("text")), ",".join(entry.get("constraint_types", [])),
    )), 1):
        result.append({
            "alias": f"FIXED-{index:03d}",
            "text": item["text"],
            "constraint_types": list(item["constraint_types"]),
            "impact_ids": list(item["impact_ids"]),
            "surface_ids": list(item["surface_ids"]),
            "source": item["source"],
        })
    return result


def _challenger_review_model_constraints(constraints):
    """Fan shared constraints into compact review records once."""
    result = []
    for source in list(constraints or []):
        if not isinstance(source, dict):
            continue
        value = {
            key: copy.deepcopy(source.get(key)) for key in (
                "alias", "text", "constraint_types", "impact_ids",
            ) if source.get(key) not in (None, "", [], {})
        }
        if value:
            result.append(value)
    return result


def _challenger_review_context(task_brain=None, verified_planning_context=None,
                               requirements=None):
    source = (
        verified_planning_context if isinstance(verified_planning_context, dict)
        else task_brain if isinstance(task_brain, dict) else {}
    )
    authority = _planner_authority_projection(
        task_brain if isinstance(task_brain, dict) else source,
        requirements,
        verified_planning_context=verified_planning_context,
    )
    compact_authority = []
    for item in authority:
        if not isinstance(item, dict):
            continue
        value = {
            key: copy.deepcopy(item.get(key)) for key in (
                "authority_type", "category", "field", "path", "symbol", "text",
                "source_ids", "requirement_ids", "structured_relation",
            ) if item.get(key) not in (None, "", [], {})
        }
        value["source_ids"] = _bounded_ids(value.get("source_ids"), 4)
        value["requirement_ids"] = _bounded_ids(value.get("requirement_ids"), 4)
        if "path" in value:
            value["path"] = _challenger_review_relative_path(value.get("path"))
        compact_authority.append({
            key: item for key, item in value.items() if item not in (None, "", [], {})
        })
    conflicts = []
    for item in _planner_conflict_projection(
        task_brain if isinstance(task_brain, dict) else source,
        verified_planning_context=verified_planning_context,
    ):
        value = copy.deepcopy(item)
        for key in ("fact_hash", "authority_fact_hash", "source_hash", "file_sha256"):
            value.pop(key, None)
        conflicts.append(value)
    stale = []
    for item in _planner_stale_projection(
        task_brain if isinstance(task_brain, dict) else source,
        verified_planning_context=verified_planning_context,
    ):
        value = copy.deepcopy(item)
        for key in ("fact_hash", "authority_fact_hash", "source_hash", "file_sha256"):
            value.pop(key, None)
        stale.append(value)
    not_evaluable = _planner_not_evaluable_projection(
        task_brain if isinstance(task_brain, dict) else source,
        verified_planning_context=verified_planning_context,
    )
    return {
        "planning_mode": source.get("planning_mode"),
        "current_authority": compact_authority[:32],
        "confirmed_conflicts": conflicts[:16],
        "stale_evidence_warnings": stale[:16],
        "not_evaluable_audit": copy.deepcopy(not_evaluable[:16]),
    }


def _challenger_review_model_context(context):
    """Compact context records without dropping review-relevant statuses."""
    value = context if isinstance(context, dict) else {}

    def records(items, limit=12):
        result = []
        seen = set()
        for source in list(items or [])[:limit]:
            if not isinstance(source, dict):
                continue
            record = {}
            for key in (
                "authority_type", "status", "record_id", "evidence_id", "classification",
                "warning", "kind", "drift_classification", "authority_fact",
                "impact_id", "surface_id", "requirement_id", "obligation_id",
                "path", "symbol", "text", "message", "reason", "type",
                "repository_evidence_ids", "evidence_refs",
            ):
                item = source.get(key)
                if item in (None, "", [], {}):
                    continue
                if key == "path":
                    item = _challenger_review_relative_path(item)
                elif key in {"text", "message", "reason", "warning", "authority_fact"}:
                    item = _compact(item, 180)
                elif key in {"repository_evidence_ids", "evidence_refs"}:
                    item = _bounded_ids(item, 4)
                record[key] = copy.deepcopy(item)
            if not record:
                continue
            semantic_identity = (
                record.get("authority_type"), record.get("status"),
                record.get("record_id"), record.get("evidence_id"),
                record.get("impact_id"), record.get("surface_id"),
                record.get("requirement_id"), record.get("obligation_id"),
                record.get("symbol"), record.get("text") or record.get("message") or record.get("reason"),
            )
            if semantic_identity not in seen:
                seen.add(semantic_identity)
                result.append(record)
        return result

    authority_records = records(value.get("current_authority"), 16)
    authority_records = [
        item for item in authority_records
        if len(item) > 1 and (
            item.get("authority_type") == "REQUIRED_INTERFACE"
            or str(item.get("path") or "").startswith("src/")
            or any(
                token in str(item.get("text") or "").casefold()
                for token in ("owner", "modify", "preserve", "interface")
            )
        )
    ]
    return {
        "planning_mode": value.get("planning_mode"),
        "current_authority": authority_records[:8],
        "confirmed_conflicts": records(value.get("confirmed_conflicts"), 8),
        "stale_evidence_warnings": records(value.get("stale_evidence_warnings"), 8),
        "not_evaluable_audit": records(value.get("not_evaluable_audit"), 8),
    }


def _challenger_review_semantic_coverage(model_payload, primary, fixed, evidence_support,
                                         obligations, constraints):
    payload = model_payload if isinstance(model_payload, dict) else {}
    impacts = list((payload.get("candidate_impact_map") or {}).get("impacts", []) or [])
    impact_ids = {str(item.get("impact_id")) for item in impacts if isinstance(item, dict)}
    requirement_ids = {
        str(item.get("requirement_id")) for item in list(payload.get("requirements", []) or [])
        if isinstance(item, dict) and item.get("requirement_id")
    }
    units = {
        "REQUIREMENT_GAP": bool(requirement_ids and payload.get("review_dimensions")),
        "SCOPE": bool(impact_ids and payload.get("review_dimensions")),
        "AUTHORITY": bool(payload.get("authority_boundary") and payload.get("surfaces")),
        "MINIMALITY": all(
            isinstance(item, dict) and item.get("necessity_status") and item.get("chosen_decision")
            for item in primary
        ) if primary else False,
        "DNT": "fixed_constraints" in payload,
        "STALE_EVIDENCE": "stale_evidence_warnings" in payload,
        "VERIFICATION": bool(evidence_support or payload.get("verification_support")),
        "PRESERVATION": bool(obligations or constraints),
        "CHALLENGE_TAXONOMY": bool(payload.get("allowed_challenge_types")),
    }
    return {
        "units": [
            {"unit_id": unit, "represented": bool(units.get(unit))}
            for unit in CHALLENGER_REVIEW_SEMANTIC_UNITS
        ],
        "represented_units": [unit for unit, present in units.items() if present],
        "uncovered_units": [unit for unit, present in units.items() if not present],
        "rate": sum(bool(item) for item in units.values()) / len(units) if units else 1.0,
    }


def build_challenger_review_projection(impact_map, requirements=None, evidence=None,
                                       surface_registry=None, task_brain=None,
                                       verified_planning_context=None):
    """Build the immutable V24.4.4 semantic projection for ImpactChallenger.

    The compiled map and its complete source records are retained in the
    artifact for local validation and reconciliation.  Only ``model_payload``
    is model-facing; it contains compact review cards and never grants
    mutation authority.
    """
    value = copy.deepcopy(impact_map if isinstance(impact_map, dict) else {})
    raw_impacts = [item for item in list(value.get("impacts", []) or []) if isinstance(item, dict)]
    requirements_value = [item for item in active_requirements(requirements) if isinstance(item, dict)]
    if not requirements_value:
        requirements_value = [
            {
                "requirement_id": item.get("requirement_id"),
                "text": item.get("text"),
                "provenance": item.get("source_provenance", USER_STATED),
            }
            for item in list((value.get("requirement_obligation_ledger") or {}).get("requirements", []) or [])
            if isinstance(item, dict) and item.get("requirement_id")
        ]
    requirements_projection = _planner_requirement_projection(requirements_value)
    obligations = _challenger_review_obligation_cards(value, requirements_value)
    classifications = []
    cards = []
    for item in raw_impacts:
        classification = _challenger_review_impact_classification(item)
        card = _challenger_review_impact_card(item, classification)
        classifications.append({
            "impact_id": str(item.get("impact_id") or ""),
            "classification": classification,
            "surface_id": str(item.get("surface_id") or item.get("canonical_surface_id") or ""),
        })
        cards.append(card)
    primary = [item for item in cards if item.get("classification") == CHALLENGER_REVIEW_PRIMARY]
    fixed = [item for item in cards if item.get("classification") == DETERMINISTIC_FIXED_CONTEXT]
    evidence_support = [item for item in cards if item.get("classification") == EVIDENCE_ONLY]
    support = [item for item in cards if item.get("classification") == CHALLENGER_REVIEW_SUPPORT]
    model_cards = [
        _challenger_review_model_impact_card(item, classification)
        for item, classification in zip(raw_impacts, [item["classification"] for item in classifications])
    ]
    model_primary = [
        item for item in model_cards if item.get("classification") == CHALLENGER_REVIEW_PRIMARY
    ]
    model_fixed = [
        item for item in model_cards if item.get("classification") == DETERMINISTIC_FIXED_CONTEXT
    ]
    model_evidence_support = [
        item for item in model_cards if item.get("classification") == EVIDENCE_ONLY
    ]
    model_support = [
        item for item in model_cards if item.get("classification") == CHALLENGER_REVIEW_SUPPORT
    ]
    constraints = _challenger_review_constraint_records(
        value, obligations, task_brain=task_brain,
        verified_planning_context=verified_planning_context,
        requirements=requirements_value,
    )
    surfaces = _challenger_review_surface_cards(value, surface_registry)
    evidence_cards = _challenger_review_evidence_cards(value, evidence)
    context = _challenger_review_context(
        task_brain=task_brain, verified_planning_context=verified_planning_context,
        requirements=requirements_value,
    )
    model_obligations = _challenger_review_model_obligation_cards(obligations)
    model_surfaces = _challenger_review_model_surface_cards(surfaces)
    model_evidence_cards = _challenger_review_model_evidence_cards(evidence_cards)
    model_context = _challenger_review_model_context(context)
    source_map_hash = challenger_review_source_map_hash(value)
    frame_coverage = value.get("impact_decision_frame_coverage")
    choice_coverage = value.get("impact_decision_choice_coverage")
    full_impact_ids = [str(item.get("impact_id")) for item in raw_impacts if item.get("impact_id")]
    full_surface_ids = [
        str(item.get("surface_id") or item.get("canonical_surface_id"))
        for item in raw_impacts
        if item.get("surface_id") or item.get("canonical_surface_id")
    ]
    model_payload = {
        "version": 1,
        "artifact_type": "ChallengerReviewRequest",
        "source_impact_map_hash": source_map_hash,
        "candidate_impact_map": {
            "version": value.get("version", 1),
            "impacts": model_cards,
        },
        "requirements": requirements_projection,
        "obligation_coverage": model_obligations,
        "review_scope": {
            "primary_impact_ids": [str(item.get("impact_id")) for item in model_primary],
            "support_impact_ids": [str(item.get("impact_id")) for item in model_support],
            "deterministic_fixed_context_impact_ids": [str(item.get("impact_id")) for item in model_fixed],
            "evidence_support_impact_ids": [str(item.get("impact_id")) for item in model_evidence_support],
        },
        "verification_support": {
            "impact_ids": [str(item.get("impact_id")) for item in model_evidence_support],
            "surface_ids": [str(item.get("surface_id")) for item in model_evidence_support if item.get("surface_id")],
            "evidence_ids": [
                str(evidence_id) for item in evidence_support
                for evidence_id in item.get("repository_evidence_ids", [])
            ],
        },
        "surfaces": model_surfaces,
        "repository_evidence": model_evidence_cards,
        "current_authority": model_context.get("current_authority", []),
        "confirmed_conflicts": model_context.get("confirmed_conflicts", []),
        "stale_evidence_warnings": model_context.get("stale_evidence_warnings", []),
        "not_evaluable_audit": model_context.get("not_evaluable_audit", []),
        "fixed_constraints": _challenger_review_model_constraints(constraints),
        "review_dimensions": list(CHALLENGER_REVIEW_SEMANTIC_UNITS),
        "allowed_challenge_types": list(CHALLENGE_TYPES),
        "authority_boundary": (
            "Review only; coverage/cards are not mutation authority. Full map/contracts remain authoritative."
        ),
        "bounds": {
            "max_challenges": MAX_CHALLENGES,
            "challenge_rounds": MAX_CHALLENGE_ROUNDS,
            "max_serialized_chars": MAX_CHALLENGER_CONTEXT_CHARS,
        },
    }
    semantic_coverage = _challenger_review_semantic_coverage(
        model_payload, primary, fixed, evidence_support, obligations, constraints,
    )
    full_map_authority = bool(
        len(full_impact_ids) == len(cards)
        and len(set(full_impact_ids)) == len(full_impact_ids)
        and set(full_impact_ids) == {
            str(item.get("impact_id")) for item in cards if item.get("impact_id")
        }
    )
    full_provenance = {
        "source_impact_map": copy.deepcopy(value),
        "source_requirements": copy.deepcopy(requirements_value),
        "source_evidence": copy.deepcopy(list(evidence or [])),
        "source_surface_registry": copy.deepcopy(surface_registry or {}),
        "source_task_brain": copy.deepcopy(task_brain or {}),
        "source_verified_planning_context": copy.deepcopy(verified_planning_context or {}),
    }
    provenance_map = {
        "source_impact_map": {
            "hash": source_map_hash,
            "source_ref": "full_provenance.source_impact_map",
        },
        "impacts": {
            str(item.get("impact_id")): {
                "source_ref": f"full_provenance.source_impact_map.impacts[{index}]",
                "surface_id": str(item.get("surface_id") or item.get("canonical_surface_id") or ""),
                "classification": classifications[index].get("classification"),
            }
            for index, item in enumerate(raw_impacts)
            if item.get("impact_id")
        },
        "surfaces": {
            str(item.get("surface_id")): {
                "source_ref": "full_provenance.source_surface_registry.surfaces",
                "path": _challenger_review_relative_path(item.get("path")),
            }
            for item in surfaces if item.get("surface_id")
        },
        "obligations": {
            str(item.get("obligation_id")): {
                "source_ref": "full_provenance.source_impact_map.impact_decision_choice_coverage.obligations",
                "assigned_impact_ids": _bounded_ids(item.get("assigned_impact_ids"), 12),
            }
            for item in obligations if item.get("obligation_id")
        },
        "evidence": {
            str(item.get("evidence_id")): {
                "source_ref": "full_provenance.source_evidence",
                "path": _challenger_review_relative_path(item.get("path")),
            }
            for item in list(evidence or [])
            if isinstance(item, dict) and item.get("evidence_id")
        },
    }
    projection = {
        "version": CHALLENGER_REVIEW_PROJECTION_VERSION,
        "artifact_type": "ChallengerReviewProjection",
        "source_impact_map_hash": source_map_hash,
        "source_impact_decision_frame_hash": value.get("impact_decision_frame_hash"),
        "source_impact_decision_choice_hash": value.get("impact_decision_choice_hash"),
        "source_frame_hash": value.get("impact_decision_frame_hash"),
        "source_choice_hash": value.get("impact_decision_choice_hash"),
        "source_planning_context_hash": value.get("source_planning_context_hash"),
        "source_mandatory_core_hash": value.get("source_mandatory_core_hash"),
        "full_impact_ids": full_impact_ids,
        "serialized_impact_ids": [str(item.get("impact_id")) for item in cards if item.get("impact_id")],
        "slot_classification": classifications,
        "primary_impacts": copy.deepcopy(primary),
        "fixed_context_impacts": copy.deepcopy(fixed),
        "evidence_support_impacts": copy.deepcopy(evidence_support),
        "support_impacts": copy.deepcopy(support),
        "obligation_coverage": copy.deepcopy(obligations),
        "coverage_status": (
            (frame_coverage or {}).get("coverage_status")
            if isinstance(frame_coverage, dict) else None
        ),
        "coverage_hash": (
            (frame_coverage or {}).get("coverage_hash")
            if isinstance(frame_coverage, dict) else None
        ),
        "choice_coverage_status": (
            (choice_coverage or {}).get("coverage_status")
            if isinstance(choice_coverage, dict) else None
        ),
        "choice_coverage_hash": (
            (choice_coverage or {}).get("coverage_hash")
            if isinstance(choice_coverage, dict) else None
        ),
        "fixed_constraints": copy.deepcopy(constraints),
        "provenance_map": provenance_map,
        "model_payload": model_payload,
        "review_semantic_coverage": semantic_coverage,
        "review_semantic_coverage_rate": semantic_coverage.get("rate", 0.0),
        "challenger_review_required_semantics_total": len(
            semantic_coverage.get("units", []) or []
        ),
        "challenger_review_required_semantics_rendered": len(
            semantic_coverage.get("represented_units", []) or []
        ),
        "challenger_review_semantic_coverage_rate": semantic_coverage.get("rate", 0.0),
        "full_map_authority_coverage": 1.0 if full_map_authority else 0.0,
        "full_map_authority_coverage_rate": 1.0 if full_map_authority else 0.0,
        "full_impact_map_semantic_coverage": 1.0 if full_map_authority else 0.0,
        "full_impact_map_provenance_reachable": 1.0 if full_map_authority and full_provenance.get("source_impact_map") else 0.0,
        "full_provenance_reachable": 1.0 if full_map_authority and full_provenance.get("source_impact_map") else 0.0,
        "full_provenance": full_provenance,
        "metrics": {
            "challenger_impacts_total": len(cards),
            "challenger_primary_impacts": len(primary),
            "challenger_fixed_context_units": len(fixed),
            "challenger_evidence_support_units": len(evidence_support),
            "challenger_projection_chars": len(_compact_json(model_payload)),
            "challenger_review_semantic_coverage": semantic_coverage.get("rate", 0.0),
        },
    }
    projection["projection_hash"] = challenger_review_projection_hash(projection)
    return projection


build_challenger_review_relevant_projection = build_challenger_review_projection


def validate_challenger_review_projection(projection, impact_map=None, requirements=None,
                                           evidence=None, surface_registry=None,
                                           task_brain=None, verified_planning_context=None):
    """Validate the immutable Challenger projection against its full source."""
    value = projection if isinstance(projection, dict) else {}
    source = impact_map
    provenance = value.get("full_provenance") if isinstance(value.get("full_provenance"), dict) else {}
    if not isinstance(source, dict):
        source = provenance.get("source_impact_map") if isinstance(provenance.get("source_impact_map"), dict) else {}
    if requirements is None:
        requirements = provenance.get("source_requirements")
    if evidence is None:
        evidence = provenance.get("source_evidence")
    if surface_registry is None:
        surface_registry = provenance.get("source_surface_registry")
    if task_brain is None:
        task_brain = provenance.get("source_task_brain")
    if verified_planning_context is None:
        verified_planning_context = provenance.get("source_verified_planning_context")
    expected = build_challenger_review_projection(
        source, requirements=requirements, evidence=evidence,
        surface_registry=surface_registry, task_brain=task_brain,
        verified_planning_context=verified_planning_context,
    )
    errors = []
    for field in (
        "version", "artifact_type", "source_impact_map_hash", "source_impact_decision_frame_hash",
        "source_impact_decision_choice_hash", "source_frame_hash", "source_choice_hash",
        "source_planning_context_hash",
        "source_mandatory_core_hash", "full_impact_ids", "serialized_impact_ids",
        "slot_classification", "obligation_coverage", "coverage_status", "coverage_hash",
        "choice_coverage_status", "choice_coverage_hash", "fixed_constraints", "provenance_map",
        "model_payload",
        "review_semantic_coverage", "review_semantic_coverage_rate", "full_map_authority_coverage",
        "challenger_review_required_semantics_total", "challenger_review_required_semantics_rendered",
        "challenger_review_semantic_coverage_rate", "full_map_authority_coverage_rate",
        "full_impact_map_semantic_coverage", "full_impact_map_provenance_reachable",
        "full_provenance_reachable", "metrics",
    ):
        if value.get(field) != expected.get(field):
            errors.append(f"projection mismatch: {field}")
    if value.get("projection_hash") != challenger_review_projection_hash(value):
        errors.append("projection hash mismatch")
    source_ids = [
        str(item.get("impact_id")) for item in list(source.get("impacts", []) or [])
        if isinstance(item, dict) and item.get("impact_id")
    ]
    serialized_ids = list(value.get("serialized_impact_ids", []) or [])
    if source_ids != serialized_ids:
        errors.append("projection does not retain every compiled impact")
    payload_value = value.get("model_payload", {})
    payload_text = _compact_json(payload_value)

    def has_nested_key(candidate, names):
        if isinstance(candidate, dict):
            if any(name in candidate for name in names):
                return True
            return any(has_nested_key(item, names) for item in candidate.values())
        if isinstance(candidate, (list, tuple)):
            return any(has_nested_key(item, names) for item in candidate)
        return False

    if "file_sha256" in payload_text or has_nested_key(
        payload_value, {"source_impact_map", "full_provenance"}
    ):
        errors.append("full source provenance leaked into model payload")
    paths = []
    for collection in (
        (value.get("model_payload") or {}).get("surfaces", []),
        (value.get("model_payload") or {}).get("repository_evidence", []),
        (value.get("model_payload") or {}).get("candidate_impact_map", {}).get("impacts", []),
    ):
        for item in list(collection or []):
            if isinstance(item, dict):
                paths.extend([item.get("path"), item.get("surface_path")])
    if any(
        isinstance(path, str) and (path.startswith("/") or path.startswith("\\")
                                   or (len(path) > 1 and path[1] == ":"))
        for path in paths if path
    ):
        errors.append("model-facing projection contains an absolute path")
    semantic = value.get("review_semantic_coverage") or {}
    if semantic.get("rate") != 1.0 or semantic.get("uncovered_units"):
        errors.append("review semantic coverage is incomplete")
    return {
        "valid": not errors,
        "status": "READY" if not errors else "CHALLENGER_REVIEW_PROJECTION_INVALID",
        "errors": list(dict.fromkeys(errors)),
        "source_impact_map_hash": value.get("source_impact_map_hash"),
        "projection_hash": value.get("projection_hash"),
        "full_impact_count": len(source_ids),
        "serialized_impact_count": len(serialized_ids),
        "review_semantic_coverage": semantic.get("rate", 0.0),
        "challenger_review_required_semantics_total": value.get(
            "challenger_review_required_semantics_total", 0,
        ),
        "challenger_review_required_semantics_rendered": value.get(
            "challenger_review_required_semantics_rendered", 0,
        ),
        "challenger_review_semantic_coverage_rate": value.get(
            "challenger_review_semantic_coverage_rate", semantic.get("rate", 0.0),
        ),
        "full_map_authority_coverage": value.get("full_map_authority_coverage", 0.0),
        "full_impact_map_semantic_coverage": value.get(
            "full_impact_map_semantic_coverage", value.get("full_map_authority_coverage", 0.0),
        ),
        "full_impact_map_provenance_reachable": value.get(
            "full_impact_map_provenance_reachable", value.get("full_provenance_reachable", 0.0),
        ),
        "full_provenance_reachable": value.get("full_provenance_reachable", 0.0),
        "model_calls": 0,
    }


validate_challenger_review_relevant_projection = validate_challenger_review_projection


def _legacy_challenger_packet_audit(packet):
    """Expose the pre-V24.4.4 representation for deterministic comparison."""
    value = packet if isinstance(packet, dict) else {}
    role_packet = value.get("role_packet") if isinstance(value.get("role_packet"), dict) else {}
    audit = role_packet.get("mandatory_payload_audit")
    return {
        "representation": "V24.4.3_FULL_COMPILED_MAP",
        "status": role_packet.get("status"),
        "packet_hash": role_packet.get("packet_hash"),
        "mandatory_payload_chars": role_packet.get("serialized_payload_chars"),
        "rendered_chars": role_packet.get("rendered_chars"),
        "hard_limit_chars": role_packet.get("hard_limit_chars"),
        "remaining_chars": role_packet.get("remaining_chars"),
        "mandatory_drops": copy.deepcopy(role_packet.get("mandatory_drops", [])),
        "optional_items_dropped_ids": copy.deepcopy(
            role_packet.get("optional_items_dropped_ids", [])
        ),
        "mandatory_payload_audit": copy.deepcopy(audit) if isinstance(audit, dict) else {},
        "mandatory_core_metrics": copy.deepcopy(role_packet.get("mandatory_core_metrics", {})),
    }


def _challenger_review_packet_budget_audit(payload, role_packet, max_chars):
    """Report the exact rendered budget without changing packet selection."""
    value = payload if isinstance(payload, dict) else {}
    role = role_packet if isinstance(role_packet, dict) else {}
    candidate = value.get("candidate_impact_map") if isinstance(value.get("candidate_impact_map"), dict) else {}
    impacts = list(candidate.get("impacts", []) or [])
    primary = [item for item in impacts if isinstance(item, dict) and item.get("classification") == CHALLENGER_REVIEW_PRIMARY]
    support = [item for item in impacts if isinstance(item, dict) and item.get("classification") == CHALLENGER_REVIEW_SUPPORT]
    fixed = [item for item in impacts if isinstance(item, dict) and item.get("classification") == DETERMINISTIC_FIXED_CONTEXT]
    evidence = [item for item in impacts if isinstance(item, dict) and item.get("classification") == EVIDENCE_ONLY]

    def encoded(item):
        return len(_compact_json(item))

    review_payload = copy.deepcopy(value)
    review_candidate = copy.deepcopy(candidate)
    review_candidate["impacts"] = primary + support
    review_payload["candidate_impact_map"] = review_candidate
    for field in (
        "fixed_constraints", "current_authority", "confirmed_conflicts",
        "stale_evidence_warnings", "not_evaluable_audit", "verification_support",
        "surfaces", "repository_evidence",
    ):
        review_payload.pop(field, None)
    fixed_payload = {
        "impacts": fixed,
        "fixed_constraints": copy.deepcopy(value.get("fixed_constraints", [])),
        "current_authority": copy.deepcopy(value.get("current_authority", [])),
    }
    verification_payload = {
        "impacts": evidence,
        "verification_support": copy.deepcopy(value.get("verification_support", {})),
        "surfaces": copy.deepcopy(value.get("surfaces", [])),
        "repository_evidence": copy.deepcopy(value.get("repository_evidence", [])),
    }
    serialized_chars = role.get("serialized_payload_chars")
    rendered_chars = role.get("rendered_chars")
    if serialized_chars is None:
        serialized_chars = encoded({**value, "packet_complete": True})
    if rendered_chars is None:
        rendered_chars = serialized_chars
    return {
        "envelope_chars": max(0, int(rendered_chars) - int(serialized_chars)),
        "review_mandatory_chars": encoded(review_payload),
        "fixed_context_chars": encoded(fixed_payload),
        "verification_support_chars": encoded(verification_payload),
        "optional_chars": 0,
        "serialized_payload_chars": int(serialized_chars),
        "exact_rendered_chars": int(rendered_chars),
        "hard_limit_chars": int(max_chars),
        "remaining_chars": int(max_chars) - int(rendered_chars),
    }


def _build_challenger_review_packet(impact_map, requirements, evidence, task_brain,
                                    surface_registry, max_chars, role, render, base_render,
                                    verified_planning_context, legacy_packet):
    projection = build_challenger_review_projection(
        impact_map, requirements=requirements, evidence=evidence,
        surface_registry=surface_registry, task_brain=task_brain,
        verified_planning_context=verified_planning_context,
    )
    projection_check = validate_challenger_review_projection(
        projection, impact_map=impact_map, requirements=requirements, evidence=evidence,
        surface_registry=surface_registry, task_brain=task_brain,
        verified_planning_context=verified_planning_context,
    )
    payload = copy.deepcopy(projection.get("model_payload", {}))
    semantic_units = [
        {
            "unit_id": str(item.get("unit_id")),
            "represented": bool(item.get("represented")),
            "source_provenance_retained": True,
            "model_semantic_required": True,
            "model_semantic_represented": bool(item.get("represented")),
        }
        for item in list(
            (projection.get("review_semantic_coverage") or {}).get("units", []) or []
        )
        if isinstance(item, dict)
    ]
    mandatory_ids = [
        "CHALLENGER_REVIEW_PROJECTION",
        *[str(item) for item in projection.get("serialized_impact_ids", []) or []],
        *[
            str(item.get("obligation_id")) for item in projection.get("obligation_coverage", [])
            if isinstance(item, dict) and item.get("obligation_id")
        ],
        "REVIEW_DIMENSIONS",
        "CHALLENGE_RESPONSE_BOUNDS",
    ]
    mandatory_payload_audit = audit_mandatory_planning_payload({
        **copy.deepcopy(payload), "packet_complete": True,
    })

    def payload_factory(selected_items, marker=True):
        value = _role_payload_factory(payload, selected_items)
        value["packet_complete"] = bool(marker)
        return value

    role_packet = build_planning_role_packet(
        role, payload, [], hard_limit=max_chars, render=render, base_render=base_render,
        source_planning_context_hash=projection.get("source_planning_context_hash"),
        mandatory_items=mandatory_ids,
        payload_factory=lambda selected: payload_factory(selected, marker=True),
        planning_core_hash=projection.get("source_mandatory_core_hash"),
        mandatory_payload_audit=mandatory_payload_audit,
        mandatory_semantic_coverage=semantic_units,
        mandatory_model_chars_before_normalization=len(_compact_json(payload)),
        mandatory_model_chars_after_normalization=len(_compact_json(payload)),
    )
    packet = role_packet.get("payload", payload)
    full_ids = list(projection.get("full_impact_ids", []) or [])
    serialized_ids = [
        str(item.get("impact_id"))
        for item in list((packet.get("candidate_impact_map") or {}).get("impacts", []) or [])
        if isinstance(item, dict) and item.get("impact_id")
    ]
    errors = list(projection_check.get("errors", []) or [])
    if serialized_ids != full_ids:
        errors.append("challenger projection did not retain every compiled impact")
    if role_packet.get("status") != "READY":
        errors.extend(role_packet.get("errors", []))
    complete = bool(role_packet.get("packet_complete")) and not errors
    legacy_audit = _legacy_challenger_packet_audit(legacy_packet)
    budget_audit = _challenger_review_packet_budget_audit(payload, role_packet, max_chars)
    observability = {
        "reviewed_impact_ids": full_ids,
        "serialized_impact_ids": serialized_ids,
        "dropped_impact_ids": [item for item in full_ids if item not in serialized_ids],
        "reviewed_surface_ids": [
            str(item.get("surface_id")) for item in projection.get("primary_impacts", [])
            + projection.get("fixed_context_impacts", [])
            + projection.get("evidence_support_impacts", [])
            + projection.get("support_impacts", [])
            if isinstance(item, dict) and item.get("surface_id")
        ],
        "packet_chars": role_packet.get("rendered_chars", 0),
        "payload_chars": len(_compact_json(packet)),
        "estimated_tokens": _estimated_tokens(
            role_packet.get("rendered_packet", _compact_json(packet))
        ),
        "packet_complete": complete,
        "projection_hash": projection.get("projection_hash"),
        "projection_metrics": copy.deepcopy(projection.get("metrics", {})),
        "review_semantic_coverage": projection.get("review_semantic_coverage_rate", 0.0),
        "full_map_authority_coverage": projection.get("full_map_authority_coverage", 0.0),
        "full_provenance_reachable": projection.get("full_provenance_reachable", 0.0),
        "packet_budget_audit": copy.deepcopy(budget_audit),
    }
    result = copy.deepcopy(packet)
    result.update({
        "packet": copy.deepcopy(packet),
        "role_packet": copy.deepcopy(role_packet),
        "observability": observability,
        "reviewed_impact_ids": full_ids,
        "serialized_impact_ids": serialized_ids,
        "dropped_impact_ids": list(observability["dropped_impact_ids"]),
        "packet_chars": role_packet.get("rendered_chars", 0),
        "estimated_tokens": observability["estimated_tokens"],
        "packet_complete": complete,
        "status": "READY" if complete else (
            role_packet.get("status") if role_packet.get("status") != "READY"
            else IMPACT_CHALLENGER_CONTEXT_INCOMPLETE
        ),
        "errors": list(dict.fromkeys(errors))[:24],
        "challenger_review_projection": copy.deepcopy(projection),
        "challenger_review_projection_validation": projection_check,
        "packet_budget_audit": copy.deepcopy(budget_audit),
        "previous_challenger_packet_audit": legacy_audit,
        # Keep the descriptive legacy name available to artifact consumers
        # without changing the existing full-map validator input.
        "legacy_payload_audit": legacy_audit,
        "full_compiled_impact_map": copy.deepcopy(impact_map),
        "model_calls": 0,
    })
    return result


def _challenger_optional_items(packet):
    """Return challenger evidence/prose units below the review authority."""
    value = packet if isinstance(packet, dict) else {}
    result = []
    sequence = 0

    def add(category, priority, path, item, index, source_ids=None, semantic_key=None):
        nonlocal sequence
        sequence += 1
        result.append({
            "item_id": f"{category.upper()}-{index + 1:03d}",
            "category": category,
            "priority": priority,
            "path": tuple(path),
            "index": index,
            "value": copy.deepcopy(item),
            "source_ids": list(source_ids or []),
            "semantic_key": semantic_key,
            "_order": sequence,
        })

    candidate = value.get("candidate_impact_map") if isinstance(value.get("candidate_impact_map"), dict) else {}
    for field, priority, count in (
        ("integration_verification", 40, 10),
        ("insufficient_evidence", 30, 6),
    ):
        for index, item in enumerate(list(candidate.get(field, []) or [])[:count]):
            add(f"candidate_{field}", priority, ("candidate_impact_map", field), item, index)
    for index, item in enumerate(list(value.get("accepted_repository_evidence", []) or [])):
        if isinstance(item, dict):
            add(
                "repository_evidence", 60, ("accepted_repository_evidence",), item, index,
                source_ids=[item.get("evidence_id")] if item.get("evidence_id") else [],
                semantic_key=str(item.get("evidence_id") or ""),
            )
    task_facts = value.get("task_facts") if isinstance(value.get("task_facts"), dict) else {}
    priorities = {
        "user_confirmed_decisions": 90, "current_owners": 60,
        "current_state_ownership": 60, "current_interfaces": 60,
        "relevant_tests": 55, "relevant_dependencies": 45,
        "acceptance_conditions": 35, "known_non_goals": 25,
    }
    for field, priority in priorities.items():
        for index, item in enumerate(list(task_facts.get(field, []) or [])):
            if isinstance(item, dict):
                add(
                    f"task_facts_{field}", priority, ("task_facts", field), item, index,
                    source_ids=_planner_source_ids(item),
                    semantic_key=_planner_record_text(item).casefold(),
                )
    for index, item in enumerate(list(value.get("stale_evidence_warnings", []) or [])):
        if isinstance(item, dict):
            add(
                "stale_warning", 30, ("stale_evidence_warnings",), item, index,
                source_ids=_planner_source_ids(item),
                semantic_key=str(item.get("record_id") or item.get("fact_hash") or ""),
            )
    for index, item in enumerate(list(value.get("not_evaluable_audit", []) or [])):
        if isinstance(item, dict):
            add(
                "not_evaluable_audit", 10, ("not_evaluable_audit",), item, index,
                source_ids=_planner_source_ids(item),
                semantic_key=str(item.get("authority_record_id") or index),
            )
    for index, item in enumerate(list(value.get("project_context", []) or [])):
        add("project_context", 20, ("project_context",), item, index, semantic_key=str(item).casefold())
    return result


def _challenger_mandatory_payload(packet):
    value = copy.deepcopy(packet if isinstance(packet, dict) else {})
    for field in (
        "accepted_repository_evidence", "task_facts", "project_context",
        "stale_evidence_warnings", "not_evaluable_audit",
    ):
        value.pop(field, None)
    candidate = value.get("candidate_impact_map")
    if isinstance(candidate, dict):
        candidate.pop("integration_verification", None)
        candidate.pop("insufficient_evidence", None)
    return value


def _trim_challenger_optional_payload(packet, max_chars):
    value = copy.deepcopy(packet)

    def size():
        return len(_compact_json(value))

    while size() > max_chars:
        project = value.get("project_context")
        if isinstance(project, list) and project:
            project.pop()
            continue
        task_facts = value.get("task_facts")
        removed = False
        if isinstance(task_facts, dict):
            for field in (
                "known_non_goals", "acceptance_conditions", "relevant_dependencies",
                "current_interfaces", "current_state_ownership", "current_owners",
                "relevant_tests", "user_confirmed_decisions",
            ):
                values = task_facts.get(field)
                if isinstance(values, list) and values:
                    values.pop()
                    removed = True
                    break
                if isinstance(values, list) and not values:
                    task_facts.pop(field, None)
            if not removed and task_facts:
                value["task_facts"] = {}
                removed = True
        if removed:
            continue
        evidence = value.get("accepted_repository_evidence")
        if isinstance(evidence, list) and evidence:
            evidence.pop()
            continue
        break
    return value


def build_challenger_packet(impact_map, requirements, evidence, task_brain=None,
                            surface_registry=None, max_chars=None, role="ImpactChallenger",
                            render=None, base_render=None, verified_planning_context=None,
                            _force_legacy=False):
    """Build a complete review packet using the exact role renderer."""
    max_chars = MAX_CHALLENGER_CONTEXT_CHARS if max_chars is None else max_chars
    max_chars = max(1, int(max_chars))
    if not _force_legacy and _challenger_review_projection_enabled(impact_map, role):
        legacy_packet = build_challenger_packet(
            impact_map, requirements, evidence, task_brain=task_brain,
            surface_registry=surface_registry, max_chars=max_chars, role=role,
            render=render, base_render=base_render,
            verified_planning_context=verified_planning_context,
            _force_legacy=True,
        )
        return _build_challenger_review_packet(
            impact_map, requirements, evidence, task_brain, surface_registry,
            max_chars, role, render, base_render, verified_planning_context,
            legacy_packet,
        )
    brain = task_brain if isinstance(task_brain, dict) else {}
    raw_impacts = list((impact_map or {}).get("impacts", []) or [])
    impacts = [
        compact for compact in (
            _review_impact_packet(item)
            for item in raw_impacts[:MAX_IMPACT_ENTRIES]
        ) if compact is not None
    ]
    impact_ids = [
        str(item.get("impact_id")) for item in raw_impacts
        if isinstance(item, dict) and item.get("impact_id")
    ]
    surface_by_id = canonical_surface_by_id(surface_registry)
    surface_ids = [
        str(item.get("surface_id") or item.get("canonical_surface_id"))
        for item in impacts
        if item.get("surface_id") or item.get("canonical_surface_id")
    ]
    reviewed_surfaces = [
        _review_surface_packet(surface_by_id[item]) for item in surface_ids if item in surface_by_id
    ]
    selected_surface_ids = [str(item.get("surface_id")) for item in reviewed_surfaces]
    packet = {
        "version": 1,
        "candidate_impact_map": {
            "version": 1,
            "task_goal": _compact((impact_map or {}).get("task_goal"), 1000),
            "impacts": impacts,
            "integration_verification": _bounded_strings(
                _list_value((impact_map or {}).get("integration_verification")), 10, 320,
            ),
            "insufficient_evidence": _bounded_strings(
                _list_value((impact_map or {}).get("insufficient_evidence")), 6, 320,
            ),
        },
        "requirements": _planner_requirement_projection(requirements),
        "surfaces": reviewed_surfaces,
        "preservation_constraints": _planner_preservation_projection(task_brain, requirements),
        "accepted_repository_evidence": _planner_evidence_projection(
            evidence, selected_surface_ids=selected_surface_ids, registry=surface_registry,
        ),
        "task_facts": _planner_task_fact_projection(task_brain),
        "project_context": _bounded_strings(
            [
                item.get("text") for item in list(brain.get("relevant_project_brain_projection", []) or [])
                if isinstance(item, dict)
            ], 8, 360,
        ),
        "bounds": {"max_challenges": MAX_CHALLENGES, "challenge_rounds": MAX_CHALLENGE_ROUNDS,
                   "max_serialized_chars": max_chars},
    }
    include_role_authority = (
        isinstance(verified_planning_context, dict)
        or any(
            isinstance(task_brain, dict) and task_brain.get(field)
            for field in (
                "current_authority", "confirmed_conflicts", "stale_evidence_warnings",
                "not_evaluable_audit", "dnt", "prohibitions",
            )
        )
    )
    if include_role_authority:
        planner_context = _planner_source_metadata(
            task_brain, verified_planning_context=verified_planning_context,
        )
        packet.update({
            "current_authority": _planner_authority_projection(
                task_brain, requirements, verified_planning_context=verified_planning_context,
            ),
            "confirmed_conflicts": _planner_conflict_projection(
                task_brain, verified_planning_context=verified_planning_context,
            ),
            "preservation_constraints": _planner_preservation_projection(
                task_brain, requirements, verified_planning_context=verified_planning_context,
            ),
            "planning_provenance": {
                key: value for key, value in planner_context.items()
                if value not in (None, "", [], {})
            },
            "stale_evidence_warnings": _planner_stale_projection(
                task_brain, verified_planning_context=verified_planning_context,
            ),
            "not_evaluable_audit": _planner_not_evaluable_projection(
                task_brain, verified_planning_context=verified_planning_context,
            ),
        })
    raw_mandatory_payload = _challenger_mandatory_payload(packet)
    mandatory_payload_audit = audit_mandatory_planning_payload(raw_mandatory_payload)
    core_source = _role_core_source(raw_mandatory_payload)
    source_metadata = _planner_source_metadata(
        task_brain, verified_planning_context=verified_planning_context,
    )
    core_provenance = (
        core_source.get("planning_provenance")
        if isinstance(core_source.get("planning_provenance"), dict) else {}
    )
    mandatory_core = build_canonical_mandatory_planning_core(
        core_source,
        project_id=(verified_planning_context or {}).get("project_id")
        if isinstance(verified_planning_context, dict) else None,
        task_id=(verified_planning_context or {}).get("task_id")
        if isinstance(verified_planning_context, dict) else None,
        source_planning_context_hash=(
            source_metadata.get("source_planning_context_hash")
            or core_provenance.get("source_planning_context_hash")
        ),
        source_task_brain_hash=(
            source_metadata.get("source_task_brain_hash")
            or core_provenance.get("source_task_brain_hash")
        ),
        source_reentry_hash=(
            source_metadata.get("source_reentry_hash")
            or core_provenance.get("source_reentry_hash")
        ),
    )
    packet = _canonical_role_model_payload(packet, mandatory_core)
    optional_items = _challenger_optional_items(packet)
    mandatory_payload = _challenger_mandatory_payload(packet)
    normalized_mandatory_value = copy.deepcopy(mandatory_payload)
    normalized_mandatory_value["packet_complete"] = True
    normalized_mandatory_chars = len(_compact_json(normalized_mandatory_value))
    mandatory_ids = [
        "CANDIDATE_IMPACT_MAP",
        *[f"IMPACT-{item.get('impact_id')}" for item in impacts if item.get("impact_id")],
        *[f"REQUIREMENT-{item.get('requirement_id')}" for item in _planner_requirement_projection(requirements)],
        *[f"SURFACE-{item}" for item in selected_surface_ids],
        "PRESERVATION_CONSTRAINTS",
    ]
    if include_role_authority:
        mandatory_ids.extend(["CURRENT_AUTHORITY", "CONFIRMED_CONFLICTS", "PLANNING_PROVENANCE"])
    if mandatory_core.get("mandatory_semantic_coverage"):
        mandatory_ids.extend([
            "CANONICAL_MANDATORY_CORE", "CURRENT_VS_DESIRED",
        ])

    def payload_factory(selected_items, marker=True):
        value = _role_payload_factory(mandatory_payload, selected_items)
        value["packet_complete"] = bool(marker)
        return value

    role_packet = build_planning_role_packet(
        role, mandatory_payload, optional_items,
        hard_limit=max_chars, render=render, base_render=base_render,
        source_planning_context_hash=(
            _planner_source_metadata(task_brain, verified_planning_context)
            .get("source_planning_context_hash")
        ),
        mandatory_items=mandatory_ids,
        payload_factory=lambda selected: payload_factory(selected, marker=True),
        planning_core_hash=mandatory_core.get("mandatory_core_hash"),
        mandatory_payload_audit=mandatory_payload_audit,
        mandatory_semantic_coverage=mandatory_core.get("mandatory_semantic_coverage", []),
        mandatory_model_chars_before_normalization=mandatory_payload_audit.get("payload_chars"),
        mandatory_model_chars_after_normalization=normalized_mandatory_chars,
        mandatory_core_metrics=mandatory_core.get("metrics"),
    )
    packet = role_packet.get("payload", {})
    packet_chars = role_packet.get("rendered_chars", len(_compact_json(packet)))
    serialized_impact_ids = [
        str(item.get("impact_id"))
        for item in packet.get("candidate_impact_map", {}).get("impacts", [])
        if item.get("impact_id")
    ]
    errors = []
    if len(raw_impacts) > MAX_IMPACT_ENTRIES:
        errors.append("challenger impact entry bound exceeded")
    if packet_chars > max_chars:
        errors.append("exact challenger review packet exceeds the rendered-size bound")
    if serialized_impact_ids != impact_ids:
        errors.append("challenger packet did not retain every reviewed impact")
    complete = bool(role_packet.get("packet_complete")) and not errors
    if packet.get("packet_complete") is not complete:
        selected_ids = set(role_packet.get("optional_items_selected", []))
        selected_optional = [
            item for item in optional_items if str(item.get("item_id")) in selected_ids
        ]
        role_packet = build_planning_role_packet(
            role, mandatory_payload, optional_items,
            hard_limit=max_chars, render=render, base_render=base_render,
            source_planning_context_hash=(
                _planner_source_metadata(task_brain, verified_planning_context)
                .get("source_planning_context_hash")
            ),
            mandatory_items=mandatory_ids,
            payload_factory=lambda chosen: (
                dict(_role_payload_factory(mandatory_payload, chosen), packet_complete=complete)
            ),
            packet_complete_override=complete,
            planning_core_hash=mandatory_core.get("mandatory_core_hash"),
            mandatory_payload_audit=mandatory_payload_audit,
            mandatory_semantic_coverage=mandatory_core.get("mandatory_semantic_coverage", []),
            mandatory_model_chars_before_normalization=mandatory_payload_audit.get("payload_chars"),
            mandatory_model_chars_after_normalization=normalized_mandatory_chars,
            mandatory_core_metrics=mandatory_core.get("metrics"),
        )
        packet = role_packet.get("payload", packet)
        packet_chars = role_packet.get("rendered_chars", packet_chars)
        complete = bool(role_packet.get("packet_complete")) and not errors
        serialized_impact_ids = [
            str(item.get("impact_id"))
            for item in packet.get("candidate_impact_map", {}).get("impacts", [])
            if item.get("impact_id")
        ]
    observability = {
        "reviewed_impact_ids": impact_ids,
        "serialized_impact_ids": serialized_impact_ids,
        "dropped_impact_ids": [item for item in impact_ids if item not in serialized_impact_ids],
        "reviewed_surface_ids": selected_surface_ids,
        "packet_chars": packet_chars,
        "payload_chars": len(_compact_json(packet)),
        "estimated_tokens": _estimated_tokens(role_packet.get("rendered_packet", _compact_json(packet))),
        "packet_complete": complete,
        "mandatory_core_hash": mandatory_core.get("mandatory_core_hash"),
        "mandatory_model_chars_before_normalization": mandatory_payload_audit.get("payload_chars"),
        "mandatory_model_chars_after_normalization": normalized_mandatory_chars,
        "mandatory_semantic_coverage": mandatory_core.get("mandatory_semantic_coverage", []),
        "role_packet": copy.deepcopy({
            key: value for key, value in role_packet.items()
            if key not in {"payload", "rendered_packet", "exact_model_input", "base_rendered_packet",
                           "mandatory_rendered_packet", "mandatory_serialized_payload"}
        }),
    }
    result = copy.deepcopy(packet)
    result.update({
        "packet": copy.deepcopy(packet),
        "role_packet": copy.deepcopy(role_packet),
        "observability": observability,
        "reviewed_impact_ids": impact_ids,
        "serialized_impact_ids": serialized_impact_ids,
        "dropped_impact_ids": list(observability["dropped_impact_ids"]),
        "packet_chars": packet_chars,
        "estimated_tokens": observability["estimated_tokens"],
        "packet_complete": complete,
        "status": "READY" if complete else (
            role_packet.get("status") if role_packet.get("status") != "READY"
            else IMPACT_CHALLENGER_CONTEXT_INCOMPLETE
        ),
        "errors": errors[:12],
        "canonical_mandatory_planning_core": copy.deepcopy(mandatory_core),
        "mandatory_payload_audit": copy.deepcopy(mandatory_payload_audit),
        "mandatory_semantic_coverage": copy.deepcopy(
            mandatory_core.get("mandatory_semantic_coverage", [])
        ),
        "mandatory_core_hash": mandatory_core.get("mandatory_core_hash"),
    })
    return result


build_complete_challenger_packet = build_challenger_packet


def build_challenger_context(impact_map, requirements, evidence, task_brain=None,
                             surface_registry=None):
    """Backward-compatible view of the complete challenger review packet."""
    result = build_challenger_packet(
        impact_map, requirements, evidence, task_brain=task_brain,
        surface_registry=surface_registry,
    )
    context = copy.deepcopy(result.get("packet", result))
    observability = result.get("observability", {})
    context["packet_observability"] = {
        key: copy.deepcopy(observability.get(key))
        for key in (
            "reviewed_impact_ids", "serialized_impact_ids", "dropped_impact_ids",
            "reviewed_surface_ids", "packet_chars", "payload_chars", "estimated_tokens",
            "packet_complete",
        )
    }
    context["packet_complete"] = bool(result.get("packet_complete"))
    return context


def _revision_optional_items(context):
    """Return optional revision evidence as complete nested semantic units."""
    value = context if isinstance(context, dict) else {}
    result = []
    sequence = 0

    def add(category, priority, path, item, index, source_ids=None, semantic_key=None):
        nonlocal sequence
        sequence += 1
        display_index = sequence if index is None else index + 1
        result.append({
            "item_id": f"{category.upper()}-{display_index:03d}",
            "category": category,
            "priority": priority,
            "path": tuple(path),
            "index": index,
            "value": copy.deepcopy(item),
            "source_ids": list(source_ids or []),
            "semantic_key": semantic_key,
            "_order": sequence,
        })

    candidate = value.get("candidate_impact_map") if isinstance(value.get("candidate_impact_map"), dict) else {}
    for field, priority in (("integration_verification", 40), ("insufficient_evidence", 30)):
        for index, item in enumerate(list(candidate.get(field, []) or [])):
            add(f"candidate_{field}", priority, ("candidate_impact_map", field), item, index)

    # Candidate-map hydration counters and version/bound labels are audit
    # presentation, not revision semantics.  They remain available as
    # complete optional field units, but do not compete with the candidate
    # decisions, validated challenges, or current planning authority for the
    # mandatory budget.  A scalar/dict field uses no list index so selecting
    # it cannot turn a field value into a malformed one-element list.
    candidate_audit_fields = (
        "canonical_surface_registry_version", "bounds", "provenance",
        "hydration_valid", "hydration_errors", "hydration_rejected_impacts",
        "impact_decisions_received", "impact_decisions_validated",
        "impact_decisions_rejected", "impact_unknown_surface_references",
        "impact_unknown_impact_seed_references", "impact_surface_evidence_mismatches",
        "impact_invented_existing_paths_rejected", "impact_invented_interfaces_rejected",
        "impact_invalid_optional_fields_rejected", "impact_invalid_requirement_references_rejected",
        "impact_seed_surface_binding_conflicts", "impact_seed_decisions_received",
        "impact_seed_decisions_validated", "impact_seed_decisions_rejected",
    )
    for field in candidate_audit_fields:
        if field in candidate and candidate.get(field) not in (None, "", [], {}):
            add(
                f"candidate_audit_{field}", 15,
                ("candidate_impact_map", field), candidate.get(field), None,
                semantic_key=field,
            )

    planning = value.get("planning_packet") if isinstance(value.get("planning_packet"), dict) else {}
    for index, item in enumerate(list(planning.get("accepted_repository_evidence", []) or [])):
        if isinstance(item, dict):
            add(
                "planning_repository_evidence", 70,
                ("planning_packet", "accepted_repository_evidence"), item, index,
                source_ids=[item.get("evidence_id")] if item.get("evidence_id") else [],
                semantic_key=str(item.get("evidence_id") or ""),
            )
    task_facts = planning.get("task_facts") if isinstance(planning.get("task_facts"), dict) else {}
    priorities = {
        "user_confirmed_decisions": 90, "current_owners": 60,
        "current_state_ownership": 60, "current_interfaces": 60,
        "relevant_tests": 55, "relevant_dependencies": 45,
        "acceptance_conditions": 35, "known_non_goals": 25,
    }
    for field, priority in priorities.items():
        for index, item in enumerate(list(task_facts.get(field, []) or [])):
            if isinstance(item, dict):
                add(
                    f"planning_task_facts_{field}", priority,
                    ("planning_packet", "task_facts", field), item, index,
                    source_ids=_planner_source_ids(item),
                    semantic_key=_planner_record_text(item).casefold(),
                )
    for index, item in enumerate(list(planning.get("stale_evidence_warnings", []) or [])):
        if isinstance(item, dict):
            add(
                "planning_stale_warning", 30,
                ("planning_packet", "stale_evidence_warnings"), item, index,
                source_ids=_planner_source_ids(item),
                semantic_key=str(item.get("record_id") or item.get("fact_hash") or ""),
            )
    for index, item in enumerate(list(planning.get("not_evaluable_audit", []) or [])):
        if isinstance(item, dict):
            add(
                "planning_not_evaluable_audit", 10,
                ("planning_packet", "not_evaluable_audit"), item, index,
                source_ids=_planner_source_ids(item),
                semantic_key=str(item.get("authority_record_id") or index),
            )
    for index, item in enumerate(list(planning.get("project_context", []) or [])):
        add(
            "planning_project_context", 20,
            ("planning_packet", "project_context"), item, index,
            semantic_key=str(item).casefold(),
        )
    return result


def _revision_mandatory_payload(context):
    value = copy.deepcopy(context if isinstance(context, dict) else {})
    candidate = value.get("candidate_impact_map")
    if isinstance(candidate, dict):
        candidate.pop("integration_verification", None)
        candidate.pop("insufficient_evidence", None)
        for field in (
            "canonical_surface_registry_version", "bounds", "provenance",
            "hydration_valid", "hydration_errors", "hydration_rejected_impacts",
            "impact_decisions_received", "impact_decisions_validated",
            "impact_decisions_rejected", "impact_unknown_surface_references",
            "impact_unknown_impact_seed_references", "impact_surface_evidence_mismatches",
            "impact_invented_existing_paths_rejected", "impact_invented_interfaces_rejected",
            "impact_invalid_optional_fields_rejected", "impact_invalid_requirement_references_rejected",
            "impact_seed_surface_binding_conflicts", "impact_seed_decisions_received",
            "impact_seed_decisions_validated", "impact_seed_decisions_rejected",
        ):
            candidate.pop(field, None)
    planning = value.get("planning_packet")
    if isinstance(planning, dict):
        for field in (
            "accepted_repository_evidence", "task_facts", "project_context",
            "stale_evidence_warnings", "not_evaluable_audit",
        ):
            planning.pop(field, None)
    return value


def build_revision_packet(context, max_chars=None, *, role="ImpactPlanReviser",
                          render=None, base_render=None, source_planning_context_hash=None):
    """Compile the bounded minimal-plan/reconciliation role packet."""
    max_chars = MAX_REVISION_CONTEXT_CHARS if max_chars is None else max(1, int(max_chars))
    value = copy.deepcopy(context if isinstance(context, dict) else {})
    raw_mandatory_payload = _revision_mandatory_payload(value)
    mandatory_payload_audit = audit_mandatory_planning_payload(raw_mandatory_payload)
    core_source = _role_core_source(raw_mandatory_payload, nested_key="planning_packet")
    source_metadata = {}
    if isinstance(core_source.get("planning_provenance"), dict):
        source_metadata = core_source.get("planning_provenance")
    if source_planning_context_hash is None:
        source_planning_context_hash = source_metadata.get("source_planning_context_hash")
    mandatory_core = build_canonical_mandatory_planning_core(
        core_source,
        project_id=core_source.get("project_id"),
        task_id=core_source.get("task_id"),
        source_planning_context_hash=source_planning_context_hash,
        source_task_brain_hash=source_metadata.get("source_task_brain_hash"),
        source_reentry_hash=source_metadata.get("source_reentry_hash"),
    )
    model_payload = _canonical_role_model_payload(
        value, mandatory_core, nested_key="planning_packet",
    )
    optional_items = _revision_optional_items(model_payload)
    mandatory_payload = _revision_mandatory_payload(model_payload)
    normalized_mandatory_value = copy.deepcopy(mandatory_payload)
    normalized_mandatory_value["packet_complete"] = True
    normalized_mandatory_chars = len(_compact_json(normalized_mandatory_value))
    candidate = value.get("candidate_impact_map") if isinstance(value.get("candidate_impact_map"), dict) else {}
    planning = value.get("planning_packet") if isinstance(value.get("planning_packet"), dict) else {}
    mandatory_ids = [
        "CANDIDATE_IMPACT_MAP",
        *[str(item.get("impact_id")) for item in candidate.get("impacts", [])
          if isinstance(item, dict) and item.get("impact_id")],
        *[str(item.get("challenge_id")) for item in value.get("validated_challenges", [])
          if isinstance(item, dict) and item.get("challenge_id")],
        *[f"REQUIREMENT-{item.get('requirement_id')}"
          for item in planning.get("requirements", []) if isinstance(item, dict)],
        *[str(item.get("surface_id")) for item in planning.get("surfaces", [])
          if isinstance(item, dict) and item.get("surface_id")],
        "PLANNING_PACKET",
    ]
    if source_planning_context_hash is None:
        provenance = planning.get("planning_provenance")
        if isinstance(provenance, dict):
            source_planning_context_hash = provenance.get("source_planning_context_hash")

    def payload_factory(selected_items, marker=True):
        payload = _role_payload_factory(mandatory_payload, selected_items)
        payload["packet_complete"] = bool(marker)
        return payload

    role_packet = build_planning_role_packet(
        role, mandatory_payload, optional_items,
        hard_limit=max_chars, render=render, base_render=base_render,
        source_planning_context_hash=source_planning_context_hash,
        mandatory_items=mandatory_ids,
        payload_factory=lambda selected: payload_factory(selected, marker=True),
        planning_core_hash=mandatory_core.get("mandatory_core_hash"),
        mandatory_payload_audit=mandatory_payload_audit,
        mandatory_semantic_coverage=mandatory_core.get("mandatory_semantic_coverage", []),
        mandatory_model_chars_before_normalization=mandatory_payload_audit.get("payload_chars"),
        mandatory_model_chars_after_normalization=normalized_mandatory_chars,
        mandatory_core_metrics=mandatory_core.get("metrics"),
    )
    packet = role_packet.get("payload", {})
    packet_chars = role_packet.get("rendered_chars", len(_compact_json(packet)))
    complete = bool(role_packet.get("packet_complete"))
    errors = list(role_packet.get("errors", []))
    if not complete and role_packet.get("status") == "READY":
        errors.append("revision packet is incomplete")
    if packet.get("packet_complete") is not complete:
        role_packet = build_planning_role_packet(
            role, mandatory_payload, optional_items,
            hard_limit=max_chars, render=render, base_render=base_render,
            source_planning_context_hash=source_planning_context_hash,
            mandatory_items=mandatory_ids,
            payload_factory=lambda chosen: (
                dict(_role_payload_factory(mandatory_payload, chosen), packet_complete=False)
            ),
            packet_complete_override=False,
            planning_core_hash=mandatory_core.get("mandatory_core_hash"),
            mandatory_payload_audit=mandatory_payload_audit,
            mandatory_semantic_coverage=mandatory_core.get("mandatory_semantic_coverage", []),
            mandatory_model_chars_before_normalization=mandatory_payload_audit.get("payload_chars"),
            mandatory_model_chars_after_normalization=normalized_mandatory_chars,
            mandatory_core_metrics=mandatory_core.get("metrics"),
        )
        packet = role_packet.get("payload", packet)
        packet_chars = role_packet.get("rendered_chars", packet_chars)
        complete = False
    observability = {
        "packet_chars": packet_chars,
        "payload_chars": len(_compact_json(packet)),
        "estimated_tokens": _estimated_tokens(role_packet.get("rendered_packet", _compact_json(packet))),
        "packet_complete": complete,
        "mandatory_core_hash": mandatory_core.get("mandatory_core_hash"),
        "mandatory_model_chars_before_normalization": mandatory_payload_audit.get("payload_chars"),
        "mandatory_model_chars_after_normalization": normalized_mandatory_chars,
        "mandatory_semantic_coverage": mandatory_core.get("mandatory_semantic_coverage", []),
        "role_packet": copy.deepcopy({
            key: item for key, item in role_packet.items()
            if key not in {"payload", "rendered_packet", "exact_model_input", "base_rendered_packet",
                           "mandatory_rendered_packet", "mandatory_serialized_payload"}
        }),
    }
    result = copy.deepcopy(packet)
    result.update({
        "packet": copy.deepcopy(packet),
        "role_packet": copy.deepcopy(role_packet),
        "packet_chars": packet_chars,
        "estimated_tokens": observability["estimated_tokens"],
        "packet_complete": complete,
        "status": "READY" if complete else (
            role_packet.get("status") if role_packet.get("status") != "READY"
            else IMPACT_PLAN_REVISION_CONTEXT_INCOMPLETE
        ),
        "errors": errors[:12] + [
            item for item in role_packet.get("errors", []) if item not in errors
        ][:12],
        "observability": observability,
        "canonical_mandatory_planning_core": copy.deepcopy(mandatory_core),
        "mandatory_payload_audit": copy.deepcopy(mandatory_payload_audit),
        "mandatory_semantic_coverage": copy.deepcopy(
            mandatory_core.get("mandatory_semantic_coverage", [])
        ),
        "mandatory_core_hash": mandatory_core.get("mandatory_core_hash"),
    })
    return result


build_minimal_plan_packet = build_revision_packet


def _impact_text(impact):
    return " ".join(str(impact.get(key, "")) for key in (
        "component", "path", "symbols", "reason", "existing_owner", "candidate_change",
        "action", "existing_interfaces_to_reuse", "preserve",
    ))


def _make_challenge(challenge_type, impacts, requirements, evidence, claim, resolution):
    return {
        "challenge_type": challenge_type,
        "impact_ids": _bounded_ids([item.get("impact_id") for item in impacts], 4),
        "surface_ids": _bounded_ids([
            item.get("surface_id") or item.get("canonical_surface_id") for item in impacts
        ], 6),
        "requirement_ids": _bounded_ids(requirements, 6),
        "repository_evidence_ids": _bounded_ids(evidence, 6),
        "claim": claim,
        "proposed_resolution": resolution,
        "blocking": True,
    }


def _verified_behavior_exists(requirement, evidence):
    requirement_terms = _domain_tokens((requirement or {}).get("text"))
    for item in bounded_evidence(evidence, MAX_CANONICAL_SURFACES * 2):
        if item.get("category") != "CURRENT_BEHAVIOR":
            continue
        fact = " ".join(str(item.get(key, "")) for key in ("fact", "symbol", "path"))
        if requirement_terms.intersection(_domain_tokens(fact)) and re.search(
            r"\b(?:already|current|currently|implements?|provides?|supports?|exists?)\b",
            fact, re.IGNORECASE,
        ):
            return True, item.get("evidence_id")
    return False, None


def evaluate_requirement_obligations(source, requirements, evidence,
                                     surface_registry=None, obligation_ledger=None):
    """Evaluate semantic coverage by obligation type, never by ID presence alone."""
    value = source if isinstance(source, dict) else {}
    ledger = obligation_ledger or build_requirement_obligation_ledger(requirements)
    obligation_records = _obligation_records(ledger)
    surface_by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    evidence_by_id = {
        item["evidence_id"]: item
        for item in bounded_evidence(evidence, MAX_CANONICAL_SURFACES * 2)
    }
    is_plan = isinstance(value.get("approved_change_nodes"), list)
    entries = list(value.get("approved_change_nodes", []) or []) if is_plan else list(
        value.get("impacts", []) or []
    )
    preservation_entries = list(value.get("preservation_only_surfaces", []) or []) if is_plan else [
        item for item in entries
        if item.get("disposition") == "PRESERVATION_ONLY"
        or item.get("necessity_status") == "PRESERVATION_ONLY"
        or item.get("impact_kind") == "PRESERVATION_ONLY"
    ]
    global_prohibitions = _bounded_strings(value.get("prohibition_constraints"), 8, 320)
    integration = _bounded_strings(value.get("integration_verification"), 12, 320)
    canonical_constraints = value.get("canonical_constraints")
    if not isinstance(canonical_constraints, dict):
        canonical_constraints = {}
    shared_preservation = [
        item for item in canonical_constraints.get("preservation", []) or []
        if isinstance(item, dict) and item.get("text")
    ]
    shared_prohibitions = [
        item for item in canonical_constraints.get("prohibitions", []) or []
        if isinstance(item, dict) and item.get("text")
    ]
    global_prohibitions.extend(
        item.get("text") for item in shared_prohibitions
        if item.get("text") not in global_prohibitions
    )
    result = []
    for obligation in obligation_records:
        requirement_id = str(obligation.get("requirement_id"))
        linked = [
            item for item in entries
            if requirement_id in {str(value) for value in item.get("requirement_ids", [])}
        ]
        linked_preservation = [
            item for item in preservation_entries
            if requirement_id in {str(value) for value in item.get("requirement_ids", [])}
        ]
        type_records = []
        for obligation_type in obligation.get("obligation_types", []):
            covered = False
            support = []
            if obligation_type == "BEHAVIOR_CHANGE":
                for item in linked:
                    if is_plan:
                        mutation = bool(item.get("mutation_required"))
                        surface_ids = [str(value) for value in item.get("target_surface_ids", [])]
                        valid_owner = any(
                            surface_by_id.get(surface_id, {}).get("kind") == "OWNER"
                            for surface_id in surface_ids
                        ) if surface_by_id else bool(surface_ids or item.get("candidate_targets"))
                        valid_new = bool(item.get("target_new_surface_proposal_ids"))
                    else:
                        mutation = (
                            item.get("disposition") == "MUST_CHANGE"
                            or item.get("necessity_status") == "MUST_CHANGE"
                        )
                        surface = surface_by_id.get(str(item.get("surface_id"))) or {} if surface_by_id else {}
                        kind = surface.get("kind") or item.get("surface_kind")
                        valid_owner = kind == "OWNER" or (not surface_by_id and item.get("impact_kind") == "BEHAVIOR_CHANGE")
                        valid_new = bool(item.get("new_surface_proposal_ids"))
                    if mutation and (valid_owner or valid_new):
                        covered = True
                        support.append(str(item.get("node_id") or item.get("impact_id")))
                if not covered:
                    exists, evidence_id = _verified_behavior_exists(obligation, evidence)
                    if exists:
                        covered = True
                        support.append(str(evidence_id))
            elif obligation_type == "TEST":
                for item in linked:
                    if is_plan:
                        disposition = item.get("disposition")
                        kind = item.get("impact_kind")
                        target_ids = item.get("target_surface_ids", [])
                        valid_test = any(
                            surface_by_id.get(str(surface_id), {}).get("kind") == "TEST"
                            for surface_id in target_ids
                        ) if surface_by_id else bool(target_ids or item.get("candidate_targets"))
                        covered_here = bool(item.get("mutation_required")) and (
                            disposition == "TEST_CHANGE" or kind == "TEST_CHANGE"
                        ) and (valid_test or bool(item.get("target_new_surface_proposal_ids")))
                    else:
                        surface = surface_by_id.get(str(item.get("surface_id"))) or {} if surface_by_id else {}
                        valid_test = (surface.get("kind") or item.get("surface_kind")) == "TEST"
                        covered_here = (
                            item.get("disposition") == "TEST_CHANGE"
                            or item.get("impact_kind") == "TEST_CHANGE"
                        ) and (valid_test or not surface_by_id or bool(item.get("new_surface_proposal_ids")))
                    if covered_here:
                        covered = True
                        support.append(str(item.get("node_id") or item.get("impact_id")))
            elif obligation_type == "PRESERVATION":
                candidates = linked + linked_preservation
                for item in candidates:
                    constraints = (
                        list(item.get("local_preservation_constraints", []) or [])
                        + list(item.get("preservation_constraints", []) or [])
                        + list(item.get("preserve", []) or [])
                    )
                    constraints.extend(
                        record.get("text") for record in shared_preservation
                        if not record.get("requirement_ids")
                        or requirement_id in {
                            str(value) for value in record.get("requirement_ids", [])
                        }
                    )
                    explicit_surface = (
                        item.get("disposition") == "PRESERVATION_ONLY"
                        or item.get("necessity_status") == "PRESERVATION_ONLY"
                        or item.get("impact_kind") == "PRESERVATION_ONLY"
                        or item in linked_preservation
                    )
                    if constraints or explicit_surface:
                        covered = True
                        support.append(str(item.get("node_id") or item.get("impact_id") or item.get("surface_id")))
            elif obligation_type == "ARCHITECTURE_REUSE":
                for item in linked:
                    interface_ids = [str(value) for value in item.get("interface_surface_ids", [])]
                    interfaces_valid = bool(interface_ids) and (
                        not surface_by_id or all(
                            surface_by_id.get(surface_id, {}).get("kind") == "INTERFACE"
                            for surface_id in interface_ids
                        )
                    )
                    surface_ids = [str(value) for value in (
                        item.get("surface_ids", []) if is_plan else [item.get("surface_id")]
                    ) if value]
                    owner_valid = (bool(surface_ids) or (not surface_by_id and bool(item.get("current_owner")))) and (
                        not surface_by_id or all(
                            surface_by_id.get(surface_id, {}).get("kind") in {"OWNER", "INTERFACE"}
                            for surface_id in surface_ids
                        )
                    )
                    explicit_reuse = (
                        item.get("disposition") == "INTERFACE_REUSE"
                        or bool(item.get("interfaces_to_reuse"))
                        or bool(item.get("existing_interfaces_to_reuse"))
                    )
                    verified_architecture = any(
                        evidence_by_id.get(str(evidence_id), {}).get("category")
                        in {"CURRENT_OWNER", "CURRENT_STATE_OWNER", "CURRENT_INTERFACE"}
                        for evidence_id in item.get(
                            "evidence_ids" if is_plan else "repository_evidence_ids", []
                        )
                    )
                    if interfaces_valid or (owner_valid and explicit_reuse) or (
                        not surface_by_id and explicit_reuse and verified_architecture
                    ):
                        covered = True
                        support.append(str(item.get("node_id") or item.get("impact_id")))
            elif obligation_type == "PROHIBITION":
                constraints = list(global_prohibitions)
                constraints.extend(
                    text for item in linked
                    for text in (
                        list(item.get("prohibition_constraints", []) or [])
                        + list(item.get("local_preservation_constraints", []) or [])
                        + list(item.get("preservation_constraints", []) or [])
                        + list(item.get("preserve", []) or [])
                    )
                )
                constraints.extend(
                    record.get("text") for record in shared_preservation + shared_prohibitions
                    if not record.get("requirement_ids")
                    or requirement_id in {
                        str(value) for value in record.get("requirement_ids", [])
                    }
                )
                covered = any(_PROHIBITION_RE.search(str(item)) for item in constraints)
                if covered:
                    support.extend(_bounded_strings(constraints, 3, 120))
            elif obligation_type == "AUTHORITY_CHANGE":
                for item in linked:
                    authority = item.get("authority_change")
                    authorized = isinstance(authority, dict) and authority.get("authorized") is True
                    if not authorized:
                        authorized = any(
                            item.get(key) is True for key in (
                                "authority_change_authorized", "allows_authority_change",
                                "explicit_authority_change",
                            )
                        )
                    mutation = (
                        bool(item.get("mutation_required")) if is_plan else
                        item.get("disposition") == "MUST_CHANGE"
                        or item.get("necessity_status") == "MUST_CHANGE"
                    )
                    if authorized and mutation:
                        covered = True
                        support.append(str(item.get("node_id") or item.get("impact_id")))
            elif obligation_type == "CROSS_CUTTING":
                covered = bool(linked and integration)
                if covered:
                    support.extend(integration[:2])
            type_records.append({
                "obligation_type": obligation_type,
                "state": "COVERED" if covered else "UNCOVERED",
                "support": _bounded_strings(support, 6, 180),
            })
        structured_assignment_ids = {
            str(identifier)
            for item in linked + linked_preservation
            for identifier in (
                list(item.get("obligation_ids", []) or [])
                + [
                    assignment.get("obligation_id")
                    for assignment in list(item.get("obligation_assignments", []) or [])
                    if isinstance(assignment, dict)
                ]
            )
            if identifier
        }
        has_structured_assignments = bool(structured_assignment_ids)
        atomic_projection = []
        for atomic in _atomic_obligations_for_requirement(obligation):
            type_record = next(
                (
                    item for item in type_records
                    if item.get("obligation_type") == atomic.get("obligation_type")
                ),
                {},
            )
            state = type_record.get("state", "UNCOVERED")
            support = list(type_record.get("support", []) or [])
            if has_structured_assignments and str(atomic.get("obligation_id")) not in structured_assignment_ids:
                # A new compiled map carries atomic IDs by construction.  If
                # it carries assignments for this requirement but omits this
                # clause, do not let an aggregate type-level hit conceal the
                # missing atomic obligation.
                state = "UNCOVERED"
                support = []
            atomic_projection.append({
                "obligation_id": atomic.get("obligation_id"),
                "requirement_id": requirement_id,
                "obligation_type": atomic.get("obligation_type"),
                "meaning": atomic.get("meaning") or atomic.get("text"),
                "state": state,
                "support": support,
                "provenance": DERIVED_PLAN_DECISION,
            })
        result.append({
            "requirement_id": requirement_id,
            "obligation_types": list(obligation.get("obligation_types", [])),
            "obligations": type_records,
            # Keep the legacy type-level view above for existing reconciliation
            # callers, while exposing the atomic source assignments explicitly
            # for V24.4 audit consumers.  No atomic clause is collapsed into a
            # generic requirement label here.
            "atomic_obligations": atomic_projection,
            "state": "COVERED" if type_records and all(
                item["state"] == "COVERED" for item in type_records
            ) else "UNCOVERED",
            "provenance": DERIVED_PLAN_DECISION,
        })
    return {
        "requirements": result,
        "requirements_covered": sum(item["state"] == "COVERED" for item in result),
        "requirements_uncovered": sum(item["state"] != "COVERED" for item in result),
        "behavior_obligations": sum(
            item["obligation_type"] == "BEHAVIOR_CHANGE"
            for record in result for item in record["obligations"]
        ),
        "behavior_obligations_covered": sum(
            item["obligation_type"] == "BEHAVIOR_CHANGE" and item["state"] == "COVERED"
            for record in result for item in record["obligations"]
        ),
        "behavior_obligations_uncovered": sum(
            item["obligation_type"] == "BEHAVIOR_CHANGE" and item["state"] != "COVERED"
            for record in result for item in record["obligations"]
        ),
        "atomic_obligations_total": sum(
            len(record.get("atomic_obligations", []) or []) for record in result
        ),
        "atomic_behavior_change_obligations": sum(
            item.get("obligation_type") == "BEHAVIOR_CHANGE"
            for record in result for item in record.get("atomic_obligations", []) or []
        ),
        "atomic_behavior_change_obligations_covered": sum(
            item.get("obligation_type") == "BEHAVIOR_CHANGE"
            and item.get("state") == "COVERED"
            for record in result for item in record.get("atomic_obligations", []) or []
        ),
        "atomic_behavior_change_obligations_uncovered": sum(
            item.get("obligation_type") == "BEHAVIOR_CHANGE"
            and item.get("state") != "COVERED"
            for record in result for item in record.get("atomic_obligations", []) or []
        ),
    }


semantic_obligation_coverage = evaluate_requirement_obligations


def _preservation_fragments(text):
    value = _compact(text, 700)
    body = re.sub(r"^\s*(?:preserve|keep|retain)\s+(?:the\s+)?", "", value, flags=re.IGNORECASE)
    parts = [item.strip(" .,;") for item in re.split(r"\s+and\s+|;", body) if item.strip(" .,;")]
    result = []
    for part in parts:
        slash = re.match(r"^([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)\s+(.+)$", part)
        if slash:
            result.extend([
                f"Preserve existing {slash.group(1)} {slash.group(3)}.",
                f"Preserve existing {slash.group(2)} {slash.group(3)}.",
            ])
        else:
            result.append(f"Preserve {part}.")
    return _bounded_strings(result or [f"Preserve {body}."], 8, 260)


def _prohibition_constraints(text):
    if not _PROHIBITION_RE.search(str(text or "")):
        return []
    value = str(text or "")
    result = [f"Do not violate this source constraint: {_compact(value, 300)}"]
    terms = _domain_tokens(value)
    if "input" in terms and "owner" in terms:
        result.append(
            "Keep the verified input owner as the sole input-state owner; "
            "do not create duplicate input state ownership."
        )
    if ({"pause", "paused", "game"} & terms) and ({"owner", "state"} & terms):
        result.append(
            "Keep the verified GameState as the sole pause-state owner; "
            "do not create another game-state owner."
        )
    return _bounded_strings(result, 6, 320)


def _integration_check_for_obligation(obligation):
    text = str(obligation.get("text", ""))
    types = set(obligation.get("obligation_types", []))
    if "BEHAVIOR_CHANGE" in types and re.search(r"\b[\w-]+/[\w-]+\b", text):
        return f"Verify the requested transition in both directions: {text}"
    if "TEST" in types:
        return f"Run and pass the relevant test obligation: {text}"
    if "PRESERVATION" in types:
        return f"Verify preserved behavior after integration: {text}"
    if "PROHIBITION" in types:
        return f"Verify ownership and prohibition constraints: {text}"
    return (
        f"Verify {obligation.get('requirement_id')} "
        f"({', '.join(obligation.get('obligation_types', []))}): {text}"
    )


def _behavior_object(text):
    return _compact(re.sub(
        r"^\s*(?:add|change|create|edit|extend|fix|implement|introduce|migrate|modify|"
        r"remove|replace|support|update)\s+",
        "", str(text or ""), flags=re.IGNORECASE,
    ), 260)


def _apply_obligation_constraints(impact_map, requirements, surface_registry=None,
                                  impact_seeds=None, obligation_ledger=None):
    revised = copy.deepcopy(impact_map if isinstance(impact_map, dict) else {})
    impacts = list(revised.get("impacts", []) or [])
    ledger = obligation_ledger or build_requirement_obligation_ledger(requirements)
    obligation_by_id = {item["requirement_id"]: item for item in _obligation_records(ledger)}
    surface_by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    seed_by_surface = {
        str(item.get("surface_id")): item for item in list(impact_seeds or [])
        if isinstance(item, dict) and item.get("surface_id")
    }
    for impact in impacts:
        surface = surface_by_id.get(str(impact.get("surface_id")), {})
        seed = seed_by_surface.get(str(impact.get("surface_id")), {})
        req_ids = list(impact.get("requirement_ids", []))
        for requirement_id in seed.get("requirement_ids", []):
            types = obligation_by_id.get(requirement_id, {}).get("obligation_types", [])
            compatible = (
                ("PRESERVATION" in types and impact.get("disposition") == "PRESERVATION_ONLY")
                or ("TEST" in types and impact.get("disposition") == "TEST_CHANGE")
                or ("ARCHITECTURE_REUSE" in types and impact.get("disposition") == "INTERFACE_REUSE")
                or (
                    "PRESERVATION" in types
                    and (impact.get("disposition") == "MUST_CHANGE" or impact.get("necessity_status") == "MUST_CHANGE")
                    and (surface.get("kind") or impact.get("surface_kind")) == "OWNER"
                )
            )
            if compatible and requirement_id not in req_ids:
                req_ids.append(requirement_id)
        impact["requirement_ids"] = _bounded_ids(req_ids, MAX_REQUIREMENT_REFS_PER_IMPACT)
        local_constraints = list(impact.get("local_preservation_constraints", []) or [])
        prohibitions = list(impact.get("prohibition_constraints", []) or [])
        is_changed_owner = (
            (impact.get("disposition") == "MUST_CHANGE" or impact.get("necessity_status") == "MUST_CHANGE")
            and (surface.get("kind") or impact.get("surface_kind")) == "OWNER"
        )
        specialized_surface_terms = set()
        for known_surface in surface_by_id.values():
            if known_surface.get("kind") not in {"PERSISTENCE", "TEST", "ENTRYPOINT"}:
                continue
            specialized_surface_terms.update(_domain_tokens(" ".join([
                str(known_surface.get("verified_fact", "")),
                str(known_surface.get("symbol", "")),
                str(known_surface.get("role", "")),
            ])))
        for requirement_id in impact["requirement_ids"]:
            obligation = obligation_by_id.get(requirement_id, {})
            text = obligation.get("text", "")
            if "PRESERVATION" in obligation.get("obligation_types", []):
                fragments = _preservation_fragments(text)
                role = str(surface.get("role") or impact.get("surface_role") or "")
                surface_terms = _domain_tokens(" ".join([
                    str(surface.get("verified_fact", "")), str(surface.get("symbol", "")), role,
                ]))
                for fragment in fragments:
                    fragment_terms = _domain_tokens(fragment)
                    if (
                        fragment_terms.intersection(surface_terms)
                        or (
                            is_changed_owner
                            and not fragment_terms.intersection(specialized_surface_terms)
                        )
                    ):
                        local_constraints.append(fragment)
            prohibitions.extend(_prohibition_constraints(text))
        if is_changed_owner and surface:
            role_label = str(surface.get("role") or "owner").replace("_OWNER", "").replace("_", " ").casefold()
            local_constraints.append(
                f"Preserve current {role_label} ownership in {surface.get('symbol')}."
            )
        impact["local_preservation_constraints"] = _bounded_strings(local_constraints, 8, 300)
        impact["preserve"] = _bounded_strings(
            list(impact.get("preserve", [])) + impact["local_preservation_constraints"], 8, 300,
        )
        impact["prohibition_constraints"] = _bounded_strings(prohibitions, 6, 320)
    revised["impacts"] = impacts
    revised["requirement_obligation_ledger"] = copy.deepcopy(ledger)
    return revised


def _seed_requirements_for_obligation(seed, obligation_type, obligation_by_id, req_by_id):
    direct = [
        str(requirement_id) for requirement_id in seed.get("requirement_ids", [])
        if obligation_type in obligation_by_id.get(str(requirement_id), {}).get("obligation_types", [])
    ]
    if direct:
        return _bounded_ids(direct, MAX_REQUIREMENT_REFS_PER_IMPACT)
    seed_text = " ".join(str(seed.get(key, "")) for key in (
        "verified_fact", "verified_symbol", "surface_role", "surface_kind",
    ))
    seed_terms = _domain_tokens(seed_text)
    matches = [
        requirement_id for requirement_id, obligation in obligation_by_id.items()
        if obligation_type in obligation.get("obligation_types", [])
        and (
            seed_terms.intersection(_domain_tokens(obligation.get("text", "")))
            or len([
                item for item in obligation_by_id.values()
                if obligation_type in item.get("obligation_types", [])
            ]) == 1
        )
        and requirement_id in req_by_id
    ]
    return _bounded_ids(matches, MAX_REQUIREMENT_REFS_PER_IMPACT)


def _seed_impact_record(seed, surface, disposition, requirement_ids, action,
                        closure_type):
    surface_id = str(surface.get("surface_id") or seed.get("surface_id") or "")
    evidence_ids = _bounded_ids(
        surface.get("evidence_ids") or seed.get("canonical_evidence_ids") or seed.get("evidence_ids"),
        MAX_EVIDENCE_REFS_PER_IMPACT,
    )
    symbol = str(surface.get("symbol") or seed.get("verified_symbol") or "")
    impact_id = normalize_impact_id(seed.get("impact_id"))
    action = _compact(action, MAX_TEXT_CHARS)
    return {
        "impact_id": impact_id,
        "surface_id": surface_id,
        "canonical_surface_id": surface_id,
        "disposition": disposition,
        "component": symbol or surface.get("role") or surface.get("path"),
        "path": _normal_path(surface.get("path") or seed.get("canonical_path")),
        "symbols": _bounded_strings([symbol] if symbol else [], 6, 160),
        "impact_kind": _impact_kind_for_disposition(disposition),
        "requirement_ids": _bounded_ids(requirement_ids, MAX_REQUIREMENT_REFS_PER_IMPACT),
        "repository_evidence_ids": evidence_ids,
        "reason": _compact(surface.get("verified_fact") or seed.get("verified_fact"), MAX_TEXT_CHARS),
        "existing_owner": symbol if surface.get("kind") == "OWNER" else "",
        "existing_interfaces_to_reuse": [],
        "interfaces_to_reuse": [],
        "interface_surface_ids": [],
        "preserve": [],
        "local_preservation_constraints": [],
        "prohibition_constraints": [],
        "candidate_change": action,
        "action": action,
        "local_verification": [],
        "verification": [],
        "test_contract": [],
        "local_test_contract": [],
        "necessity_status": {
            "MUST_CHANGE": "MUST_CHANGE",
            "PRESERVATION_ONLY": "PRESERVATION_ONLY",
        }.get(disposition, "CANDIDATE"),
        "new_surface_proposal_ids": [],
        "surface_kind": surface.get("kind") or seed.get("surface_kind"),
        "surface_role": surface.get("role") or seed.get("surface_role"),
        "owner_surface_id": surface.get("owner_surface_id") or seed.get("owner_surface_id"),
        "closure_metadata": {
            "closure_type": closure_type,
            "requirement_ids": _bounded_ids(requirement_ids, 6),
            "surface_id": surface_id,
            "seed_id": seed.get("seed_id"),
            "provenance": DERIVED_PLAN_DECISION,
        },
        "provenance": DERIVED_PLAN_DECISION,
    }


def _mark_obligation_closure(impact, requirement_ids, surface_id, seed_id, closure_type):
    impact["requirement_ids"] = _bounded_ids(
        list(impact.get("requirement_ids", [])) + list(requirement_ids),
        MAX_REQUIREMENT_REFS_PER_IMPACT,
    )
    impact["closure_metadata"] = {
        "closure_type": closure_type,
        "requirement_ids": _bounded_ids(requirement_ids, 6),
        "surface_id": surface_id,
        "seed_id": seed_id,
        "provenance": DERIVED_PLAN_DECISION,
    }
    impact["provenance"] = DERIVED_PLAN_DECISION


def _synthesize_obligation_impacts(impact_map, requirements, evidence,
                                   surface_registry=None, impact_seeds=None,
                                   obligation_ledger=None):
    """Restore deterministic canonical responsibilities omitted by the model."""
    revised = copy.deepcopy(impact_map if isinstance(impact_map, dict) else {})
    if not surface_registry or not impact_seeds:
        return revised, []
    ledger = obligation_ledger or build_requirement_obligation_ledger(requirements)
    records = _obligation_records(ledger)
    obligation_by_id = {str(item.get("requirement_id")): item for item in records}
    req_by_id = {item["requirement_id"]: item for item in active_requirements(requirements)}
    surface_by_id = canonical_surface_by_id(surface_registry)
    impacts = list(revised.get("impacts", []) or [])
    by_surface = {
        str(item.get("surface_id")): item for item in impacts
        if isinstance(item, dict) and item.get("surface_id")
    }
    seeds = [item for item in list(impact_seeds or []) if isinstance(item, dict)]
    actions = []

    def apply_seed(seed, obligation_type, disposition, action, closure_type,
                   only_kinds=None, convert_existing=True):
        surface = surface_by_id.get(str(seed.get("surface_id")))
        if not surface or (only_kinds and surface.get("kind") not in only_kinds):
            return None
        requirement_ids = _seed_requirements_for_obligation(
            seed, obligation_type, obligation_by_id, req_by_id,
        )
        if not requirement_ids:
            return None
        surface_id = str(surface.get("surface_id"))
        target = by_surface.get(surface_id)
        if target is None:
            if len(impacts) >= MAX_IMPACT_ENTRIES:
                return None
            target = _seed_impact_record(
                seed, surface, disposition, requirement_ids, action, closure_type,
            )
            impacts.append(target)
            by_surface[surface_id] = target
            actions.append({
                "action": "SYNTHESIZED",
                "closure_type": closure_type,
                "impact_id": target.get("impact_id"),
                "surface_id": surface_id,
                "requirement_ids": list(requirement_ids),
                "seed_id": seed.get("seed_id"),
                "provenance": DERIVED_PLAN_DECISION,
            })
            return target
        if convert_existing:
            linked_types = {
                obligation_type_name
                for requirement_id in target.get("requirement_ids", [])
                for obligation_type_name in obligation_by_id.get(str(requirement_id), {}).get("obligation_types", [])
            }
            # A persistence surface with an independently required behavior
            # mutation remains a mutation target; its preservation duty is
            # carried as a constraint instead of being silently collapsed.
            if not (
                obligation_type == "PRESERVATION"
                and "BEHAVIOR_CHANGE" in linked_types
                and _impact_claims_mutation(target)
            ):
                target["disposition"] = disposition
                target["impact_kind"] = _impact_kind_for_disposition(disposition)
                target["necessity_status"] = {
                    "MUST_CHANGE": "MUST_CHANGE",
                    "PRESERVATION_ONLY": "PRESERVATION_ONLY",
                }.get(disposition, "CANDIDATE")
        _mark_obligation_closure(
            target, requirement_ids, surface_id, seed.get("seed_id"), closure_type,
        )
        if disposition == "PRESERVATION_ONLY":
            target["preserve"] = _bounded_strings(
                list(target.get("preserve", []))
                + [req_by_id[item]["text"] for item in requirement_ids if item in req_by_id],
                8, 300,
            )
            target["candidate_change"] = (
                "No mutation planned; preserve the verified current behavior."
            )
            target["action"] = target["candidate_change"]
        elif disposition == "TEST_CHANGE":
            target["candidate_change"] = _compact(
                action or "Update or add focused coverage at the verified test boundary.",
                MAX_TEXT_CHARS,
            )
            target["action"] = target["candidate_change"]
            target["local_verification"] = _bounded_strings(
                list(target.get("local_verification", []))
                + [req_by_id[item]["text"] for item in requirement_ids if item in req_by_id],
                6, 300,
            )
        elif disposition == "INTERFACE_REUSE":
            target["candidate_change"] = _compact(action, MAX_TEXT_CHARS)
            target["action"] = target["candidate_change"]
            target["interfaces_to_reuse"] = _bounded_ids(
                list(target.get("interfaces_to_reuse", [])) + [surface_id], 6,
            )
            target["interface_surface_ids"] = list(target["interfaces_to_reuse"])
            target["existing_interfaces_to_reuse"] = _bounded_strings(
                list(target.get("existing_interfaces_to_reuse", []))
                + [surface.get("symbol")], 6, 180,
            )
        return target

    # Preservation and test duties are restored from their specialized
    # canonical surfaces before behavior closure chooses a mutation anchor.
    for seed in seeds:
        if seed.get("surface_kind") == "PERSISTENCE":
            apply_seed(
                seed, "PRESERVATION", "PRESERVATION_ONLY",
                "No mutation planned; preserve the verified persistence surface.",
                "OBLIGATION_CLOSURE_PRESERVATION", {"PERSISTENCE"},
            )
    for seed in seeds:
        if seed.get("surface_kind") == "TEST":
            apply_seed(
                seed, "TEST", "TEST_CHANGE",
                "Update or add focused coverage at the verified test boundary.",
                "OBLIGATION_CLOSURE_TEST", {"TEST"},
            )

    # A newly confirmed preservation requirement may belong to the changed
    # canonical owner rather than to a persistence surface.  Attach it as a
    # local constraint without converting an independently required behavior
    # mutation into a non-mutating preservation node.
    for seed in seeds:
        if seed.get("surface_kind") != "OWNER":
            continue
        requirement_ids = _seed_requirements_for_obligation(
            seed, "PRESERVATION", obligation_by_id, req_by_id,
        )
        target = by_surface.get(str(seed.get("surface_id")))
        if not requirement_ids or target is None:
            continue
        linked_types = {
            obligation_type_name
            for requirement_id in target.get("requirement_ids", [])
            for obligation_type_name in obligation_by_id.get(str(requirement_id), {}).get("obligation_types", [])
        }
        linked_types.update(
            obligation_type_name
            for requirement_id in seed.get("requirement_ids", [])
            for obligation_type_name in obligation_by_id.get(str(requirement_id), {}).get("obligation_types", [])
        )
        _mark_obligation_closure(
            target, requirement_ids, str(seed.get("surface_id")),
            seed.get("seed_id"), "OBLIGATION_CLOSURE_PRESERVATION",
        )
        target["preserve"] = _bounded_strings(
            list(target.get("preserve", []))
            + [req_by_id[item]["text"] for item in requirement_ids if item in req_by_id],
            8, 300,
        )
        if "BEHAVIOR_CHANGE" not in linked_types:
            target["disposition"] = "PRESERVATION_ONLY"
            target["impact_kind"] = "PRESERVATION_ONLY"
            target["necessity_status"] = "PRESERVATION_ONLY"
        actions.append({
            "action": "ATTACHED",
            "closure_type": "OBLIGATION_CLOSURE_PRESERVATION",
            "impact_id": target.get("impact_id"),
            "surface_id": seed.get("surface_id"),
            "requirement_ids": list(requirement_ids),
            "seed_id": seed.get("seed_id"),
            "provenance": DERIVED_PLAN_DECISION,
        })

    # Restore every verified interface seed linked to an architecture-reuse
    # obligation.  These are inspect/reuse responsibilities, never product
    # mutation anchors.
    for seed in seeds:
        if seed.get("surface_kind") == "INTERFACE":
            apply_seed(
                seed, "ARCHITECTURE_REUSE", "INTERFACE_REUSE",
                f"Reuse the verified interface {seed.get('verified_symbol') or seed.get('surface_id')}.",
                "OBLIGATION_CLOSURE_REUSE", {"INTERFACE"},
            )

    revised["impacts"] = impacts[:MAX_IMPACT_ENTRIES]
    revised["obligation_impacts_synthesized"] = int(
        revised.get("obligation_impacts_synthesized", 0) or 0
    ) + sum(item.get("action") == "SYNTHESIZED" for item in actions)
    revised["obligation_closure_actions"] = actions
    revised["prohibition_constraints"] = _bounded_strings([
        constraint
        for obligation in records
        for constraint in _prohibition_constraints(obligation.get("text"))
    ], 8, 320)

    # Make verified interfaces available on a changed owner even if the model
    # omitted the separate interface decisions.  The interface identities
    # still come only from the canonical registry.
    by_surface = {
        str(item.get("surface_id")): item for item in revised["impacts"]
        if isinstance(item, dict) and item.get("surface_id")
    }
    reuse_requirement_ids = {
        str(item.get("requirement_id")) for item in records
        if "ARCHITECTURE_REUSE" in item.get("obligation_types", [])
    }
    interface_surfaces = [
        item for item in surface_by_id.values() if item.get("kind") == "INTERFACE"
    ]
    for target in revised["impacts"]:
        if _impact_surface_kind(target, surface_by_id) != "OWNER":
            continue
        target_requirements = {str(item) for item in target.get("requirement_ids", [])}
        if not (
            target_requirements.intersection(reuse_requirement_ids)
            or target.get("disposition") == "MUST_CHANGE"
        ):
            continue
        interface_ids = list(target.get("interfaces_to_reuse", []))
        for interface in interface_surfaces:
            seed = next((item for item in seeds if str(item.get("surface_id")) == str(interface.get("surface_id"))), {})
            seed_reqs = {str(item) for item in seed.get("requirement_ids", [])}
            if (
                interface.get("owner_surface_id") == target.get("surface_id")
                or seed_reqs.intersection(reuse_requirement_ids | target_requirements)
            ):
                interface_ids.append(str(interface.get("surface_id")))
        interface_ids = _bounded_ids(interface_ids, 6)
        target["interfaces_to_reuse"] = interface_ids
        target["interface_surface_ids"] = list(interface_ids)
        target["existing_interfaces_to_reuse"] = _bounded_strings([
            surface_by_id[item].get("symbol") for item in interface_ids if item in surface_by_id
        ], 6, 180)
    return revised, actions


def close_behavior_obligation_gaps(impact_map, requirements, evidence,
                                   surface_registry=None, impact_seeds=None,
                                   obligation_ledger=None):
    """Promote exactly one safe canonical owner for each open behavior duty."""
    revised = copy.deepcopy(impact_map if isinstance(impact_map, dict) else {})
    ledger = obligation_ledger or build_requirement_obligation_ledger(requirements)
    coverage = evaluate_requirement_obligations(
        revised, requirements, evidence, surface_registry, ledger,
    )
    open_behavior = {
        record["requirement_id"] for record in coverage["requirements"]
        if any(
            item["obligation_type"] == "BEHAVIOR_CHANGE" and item["state"] == "UNCOVERED"
            for item in record["obligations"]
        )
    }
    surface_by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    impact_by_id = {
        normalize_impact_id(item.get("impact_id")): item
        for item in revised.get("impacts", []) if isinstance(item, dict)
    }
    impact_by_surface = {
        str(item.get("surface_id")): item
        for item in revised.get("impacts", []) if isinstance(item, dict) and item.get("surface_id")
    }
    req_by_id = {item["requirement_id"]: item for item in active_requirements(requirements)}
    obligation_by_id = {
        str(item.get("requirement_id")): item
        for item in _obligation_records(ledger)
    }
    actions = []
    for requirement_id in sorted(open_behavior):
        exists, _ = _verified_behavior_exists(req_by_id.get(requirement_id, {}), evidence)
        if exists:
            continue
        candidates = []
        for seed in list(impact_seeds or []):
            seed_requirement_ids = set(str(item) for item in seed.get("requirement_ids", []))
            if requirement_id not in seed_requirement_ids:
                # Recompute the typed seed hint rather than trusting a weak
                # model's partial relationship list.
                seed_requirement_ids.update(_seed_requirements_for_obligation(
                    seed, "BEHAVIOR_CHANGE", obligation_by_id, req_by_id,
                ))
            if requirement_id not in seed_requirement_ids:
                continue
            surface = surface_by_id.get(str(seed.get("surface_id"))) if surface_by_id else None
            if not surface or surface.get("kind") != "OWNER":
                continue
            target = impact_by_id.get(normalize_impact_id(seed.get("impact_id"))) or impact_by_surface.get(
                str(seed.get("surface_id"))
            )
            if target is None:
                # Preserve the v18.3 ambiguity guard for a completely empty
                # map.  A partial planner map may be completed from seeds,
                # but an empty map has not established any usable planner
                # responsibility to reconcile.
                if not revised.get("impacts"):
                    continue
                if len(revised.get("impacts", []) or []) >= MAX_IMPACT_ENTRIES:
                    continue
                target = _seed_impact_record(
                    seed, surface, "VERIFY_ONLY", [requirement_id],
                    "Use the verified current owner for the linked behavior responsibility.",
                    "OBLIGATION_CLOSURE_BEHAVIOR",
                )
                target["impact_kind"] = "BEHAVIOR_CHANGE"
                target["disposition"] = "VERIFY_ONLY"
                target["necessity_status"] = "CANDIDATE"
                revised.setdefault("impacts", []).append(target)
                impact_by_id[normalize_impact_id(target.get("impact_id"))] = target
                impact_by_surface[str(target.get("surface_id"))] = target
                revised["obligation_impacts_synthesized"] = int(
                    revised.get("obligation_impacts_synthesized", 0) or 0
                ) + 1
            if target.get("disposition") in {"PRESERVATION_ONLY", "TEST_CHANGE"}:
                continue
            if _impact_surface_kind(target, surface_by_id) in {
                "TEST", "PERSISTENCE", "ENTRYPOINT", "INTERFACE",
            }:
                continue
            candidates.append((seed, surface, target))
        # An owner whose existing interface already accounts for all of the
        # requirement terms visible on that owner is a reuse surface, not the
        # missing mutation anchor, when another owner candidate exists.
        if len(candidates) > 1:
            filtered = []
            requirement_terms = _domain_tokens(req_by_id.get(requirement_id, {}).get("text"))
            for seed, surface, target in candidates:
                owner_terms = requirement_terms.intersection(_domain_tokens(
                    " ".join([str(surface.get("verified_fact", "")), str(surface.get("symbol", ""))])
                ))
                interface_terms = set()
                for interface in surface_by_id.values():
                    if interface.get("kind") == "INTERFACE" and interface.get("owner_surface_id") == surface.get("surface_id"):
                        interface_terms.update(_domain_tokens(
                            " ".join([str(interface.get("verified_fact", "")), str(interface.get("symbol", ""))])
                        ))
                if owner_terms and owner_terms.issubset(interface_terms):
                    continue
                filtered.append((seed, surface, target))
            if filtered:
                candidates = filtered
        unique = {
            str(surface.get("surface_id")): (seed, surface, target)
            for seed, surface, target in candidates
        }
        if len(unique) != 1:
            continue
        seed, surface, target = next(iter(unique.values()))
        target["disposition"] = "MUST_CHANGE"
        target["impact_kind"] = "BEHAVIOR_CHANGE"
        target["necessity_status"] = "MUST_CHANGE"
        target["requirement_ids"] = _bounded_ids(
            list(target.get("requirement_ids", [])) + [requirement_id],
            MAX_REQUIREMENT_REFS_PER_IMPACT,
        )
        related_ids = {requirement_id}
        for relationship in seed.get("requirement_relationships", []):
            if relationship.get("requirement_id") == requirement_id:
                related_ids.add(str(relationship.get("companion_requirement_id")))
        interface_ids = list(target.get("interfaces_to_reuse", []))
        for interface in surface_by_id.values():
            if interface.get("kind") != "INTERFACE":
                continue
            same_owner = interface.get("owner_surface_id") == surface.get("surface_id")
            linked_interface_impact = impact_by_surface.get(str(interface.get("surface_id")), {})
            linked_requirements = {str(item) for item in linked_interface_impact.get("requirement_ids", [])}
            interface_seed = next(
                (
                    item for item in list(impact_seeds or [])
                    if str(item.get("surface_id")) == str(interface.get("surface_id"))
                ),
                {},
            )
            seeded_requirements = {str(item) for item in interface_seed.get("requirement_ids", [])}
            if same_owner or related_ids.intersection(linked_requirements | seeded_requirements):
                interface_ids.append(str(interface.get("surface_id")))
        target["interfaces_to_reuse"] = _bounded_ids(interface_ids, 6)
        target["interface_surface_ids"] = list(target["interfaces_to_reuse"])
        target["existing_interfaces_to_reuse"] = _bounded_strings([
            surface_by_id[item].get("symbol") for item in target["interfaces_to_reuse"]
            if item in surface_by_id
        ], 6, 180)
        action = (
            f"Extend verified existing owner {surface.get('symbol')} for "
            f"{_behavior_object(req_by_id[requirement_id]['text'])} "
            f"({requirement_id}), reusing canonical interfaces."
        )
        target["candidate_change"] = _compact(action, MAX_TEXT_CHARS)
        target["action"] = target["candidate_change"]
        target["local_verification"] = _bounded_strings(
            list(target.get("local_verification", [])) + [req_by_id[requirement_id]["text"]], 6, 300,
        )
        target["closure_metadata"] = {
            "closure_type": "OBLIGATION_CLOSURE_BEHAVIOR",
            "requirement_ids": [requirement_id],
            "surface_id": surface.get("surface_id"),
            "seed_id": seed.get("seed_id"),
            "provenance": DERIVED_PLAN_DECISION,
        }
        actions.append(copy.deepcopy(target["closure_metadata"]))
    revised["impacts"] = list(revised.get("impacts", []))[:MAX_IMPACT_ENTRIES]
    revised["deterministic_behavior_anchor_promotions"] = len(actions)
    revised["behavior_anchor_closure_actions"] = actions
    return revised, actions


def deterministic_challenges(impact_map, requirements, evidence, surface_registry=None):
    """Add bounded deterministic falsification pressure around the model round."""
    impacts = list((impact_map or {}).get("impacts", []) or [])
    reqs = active_requirements(requirements)
    req_by_id = {item["requirement_id"]: item for item in reqs}
    facts = bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    evidence_by_id = {item["evidence_id"]: item for item in facts}
    challenges = []

    def add(value):
        if len(challenges) >= MAX_CHALLENGES:
            return
        key = (
            value.get("challenge_type"), tuple(value.get("impact_ids", [])),
            tuple(value.get("requirement_ids", [])), tuple(value.get("repository_evidence_ids", [])),
        )
        if any((
            item.get("challenge_type"), tuple(item.get("impact_ids", [])),
            tuple(item.get("requirement_ids", [])), tuple(item.get("repository_evidence_ids", [])),
        ) == key for item in challenges):
            return
        value["challenge_id"] = f"CH-D-{len(challenges) + 1:03d}"
        challenges.append(value)

    for impact in impacts:
        req_refs = [str(item) for item in impact.get("requirement_ids", [])]
        evidence_refs = [str(item) for item in impact.get("repository_evidence_ids", [])]
        linked_requirements = [req_by_id[item] for item in req_refs if item in req_by_id]
        linked_evidence = [evidence_by_id[item] for item in evidence_refs if item in evidence_by_id]
        text = _impact_text(impact)
        if impact.get("necessity_status") == "MUST_CHANGE" and (
            not linked_requirements
            or (not linked_evidence and not impact.get("new_surface_proposal_ids"))
        ):
            add(_make_challenge(
                "UNSUPPORTED_NECESSITY", [impact], req_refs, evidence_refs,
                "The MUST_CHANGE claim is not supported by valid requirement and repository evidence references.",
                "Remove the mutation claim or classify the surface as insufficient evidence.",
            ))
        persistence_link = any(item.get("category") == "CURRENT_PERSISTENCE" for item in linked_evidence)
        if (
            persistence_link
            and impact.get("disposition") != "PRESERVATION_ONLY"
            and impact.get("impact_kind") != "PRESERVATION_ONLY"
        ):
            add(_make_challenge(
                "UNSUPPORTED_NECESSITY", [impact], req_refs, evidence_refs,
                "The evidence establishes a preservation surface, not a necessary mutation.",
                "Retain the surface as PRESERVATION_ONLY and do not mutate it.",
            ))
        requirement_terms = _tokens(" ".join(item["text"] for item in linked_requirements))
        evidence_terms = _tokens(" ".join(
            str(item.get(key, "")) for item in linked_evidence for key in ("fact", "path", "symbol")
        ))
        impact_terms = _tokens(text)
        if (
            linked_requirements and linked_evidence
            and impact.get("necessity_status") in {"MUST_CHANGE", "CANDIDATE"}
            and not (requirement_terms & impact_terms)
            and not (requirement_terms & evidence_terms)
        ):
            add(_make_challenge(
                "UNRELATED_CHANGE", [impact], req_refs, evidence_refs,
                "The proposed surface has no semantic relationship to its cited Source Requirement.",
                "Exclude the unrelated surface from the mutation plan.",
            ))
        state_facts = [item for item in linked_evidence if item.get("category") == "CURRENT_STATE_OWNER"]
        duplicate_state_claim = _impact_implies_duplicate_owner(impact) and bool(re.search(
            r"\b(?:pause|paused|state|owner)\b", text, re.IGNORECASE,
        ))
        if state_facts and duplicate_state_claim:
            verified_owners = {
                str(item.get("symbol", "")).split(".", 1)[0]
                for item in state_facts if item.get("symbol")
            }
            proposed_owner = str(impact.get("component") or impact.get("existing_owner") or "")
            explicit_duplicate = bool(re.search(
                r"\b(?:add|create|introduce)\b.{0,60}\b(?:paused?|pause state|state)\b",
                text, re.IGNORECASE,
            ))
            if verified_owners and (proposed_owner not in verified_owners or explicit_duplicate):
                add(_make_challenge(
                    "DUPLICATE_OWNERSHIP_RISK", [impact], req_refs, evidence_refs,
                    "The candidate introduces state outside the verified authoritative state owner.",
                    "Keep state in the verified owner and reuse its existing transition interface.",
                ))
                add(_make_challenge(
                    "WRONG_OWNER", [impact], req_refs, evidence_refs,
                    "The proposed state responsibility conflicts with current ownership evidence.",
                    "Assign the state transition to the verified current owner.",
                ))
        interface_facts = [item for item in linked_evidence if item.get("category") == "CURRENT_INTERFACE"]
        reuse = list(impact.get("existing_interfaces_to_reuse", []) or [])
        registry_interfaces = []
        if surface_registry and impact.get("surface_id"):
            target_surface = canonical_surface_by_id(surface_registry).get(str(impact.get("surface_id")))
            if target_surface:
                registry_interfaces = [
                    item for item in surface_registry.get("surfaces", [])
                    if item.get("kind") == "INTERFACE"
                    and item.get("owner_surface_id") == target_surface.get("surface_id")
                ]
        if (interface_facts or registry_interfaces) and impact.get("disposition") != "INTERFACE_REUSE" and (
            _NEW_INTERFACE_RE.search(text) or not reuse
        ):
            challenge_evidence = list(dict.fromkeys(
                evidence_refs + [
                    evidence_id for item in registry_interfaces
                    for evidence_id in item.get("evidence_ids", [])
                ]
            ))
            add(_make_challenge(
                "INTERFACE_REUSE_MISSED", [impact], req_refs, challenge_evidence,
                "A verified current interface is available but the candidate does not clearly reuse it.",
                "Reuse the cited verified interface unless evidence demonstrates it is insufficient.",
            ))

    obligation_ledger = build_requirement_obligation_ledger(reqs)
    semantic = evaluate_requirement_obligations(
        impact_map, reqs, evidence, surface_registry, obligation_ledger,
    )
    semantic_by_id = {
        item["requirement_id"]: item for item in semantic.get("requirements", [])
    }
    test_requirements = [
        item for item in reqs
        if "TEST" in next(
            (record.get("obligation_types", []) for record in _obligation_records(obligation_ledger)
             if record.get("requirement_id") == item["requirement_id"]), []
        )
    ]
    test_facts = [item for item in facts if item.get("category") == "CURRENT_TEST"]
    test_impacts = [item for item in impacts if item.get("impact_kind") == "TEST_CHANGE"]
    if test_requirements and test_facts and not test_impacts:
        add(_make_challenge(
            "TEST_GAP", [], [item["requirement_id"] for item in test_requirements],
            [item["evidence_id"] for item in test_facts],
            "Behavior changes have no explicit test responsibility despite a test requirement and current test evidence.",
            "Add a focused TEST_CHANGE responsibility using the verified test surface.",
        ))

    for requirement in reqs:
        requirement_semantic = semantic_by_id.get(requirement["requirement_id"], {})
        if requirement_semantic.get("state") == "COVERED":
            continue
        related = [
            item for item in facts
            if _tokens(requirement["text"]) & _tokens(
                " ".join(str(item.get(key, "")) for key in ("fact", "path", "symbol"))
            )
        ]
        add(_make_challenge(
            "REQUIREMENT_GAP", [], [requirement["requirement_id"]],
            [item["evidence_id"] for item in related[:6]],
            "An active Source Requirement has an uncovered semantic obligation.",
            "Add type-correct evidence-supported coverage or leave the plan incomplete.",
        ))
    return normalize_challenges({"challenges": challenges}, source="DETERMINISTIC")


def _impact_surface_kind(impact, surface_by_id=None):
    surface_by_id = surface_by_id or {}
    surface = surface_by_id.get(str((impact or {}).get("surface_id")), {})
    return surface.get("kind") or (impact or {}).get("surface_kind")


_NON_MUTATING_RESPONSIBILITIES = frozenset({
    "INTERFACE_REUSE", "PRESERVATION_ONLY", "VERIFY_ONLY", "TEST_REFERENCE",
    "TEST_CHANGE",
})


def _impact_implies_duplicate_owner(impact):
    value = impact if isinstance(impact, dict) else {}
    text = " ".join((_impact_text(value), str(value.get("goal", ""))))
    if re.search(
        r"\b(?:do not|don't|must not|never|without)\b.{0,50}"
        r"\b(?:add|create|introduce|new|another|second|duplicate|additional|extra)\b",
        text, re.IGNORECASE,
    ):
        return False
    return bool(
        _NEW_OWNER_RE.search(text)
        or re.search(
            r"\b(?:new|another|second|duplicate|additional|extra)\b"
            r".{0,80}\b(?:owner|state|store|controller|field|flag)\b",
            text, re.IGNORECASE,
        )
    )


def _impact_claims_mutation(impact):
    """Return whether an impact claims an existing/new-surface mutation."""
    value = impact if isinstance(impact, dict) else {}
    disposition = str(value.get("disposition", "")).upper()
    necessity = str(value.get("necessity_status", "")).upper()
    if disposition in _NON_MUTATING_RESPONSIBILITIES:
        return False
    if str(value.get("impact_kind", "")).upper() in {
        "PRESERVATION_ONLY", "INTERFACE_REUSE", "CROSS_CUTTING_VERIFICATION",
        "TEST_CHANGE",
    }:
        return False
    if disposition == "MUST_CHANGE" or necessity == "MUST_CHANGE":
        return True
    if value.get("mutation_required"):
        return True
    proposal_ids = _list_value(value.get("new_surface_proposal_ids"))
    return bool(proposal_ids)


def _challenge_requirement_types(challenge, req_by_id, obligation_ledger=None):
    records = {
        item.get("requirement_id"): item
        for item in _obligation_records(obligation_ledger or list(req_by_id.values()))
    }
    return {
        obligation_type
        for requirement_id in challenge.get("requirement_ids", [])
        for obligation_type in records.get(requirement_id, {}).get("obligation_types", [])
    }


def _test_responsibility_exists(impacts, requirement_ids, surface_by_id=None):
    wanted = {str(item) for item in requirement_ids}
    surface_by_id = surface_by_id or {}
    for impact in list(impacts or []):
        if not wanted.intersection(str(item) for item in impact.get("requirement_ids", [])):
            continue
        kind = _impact_surface_kind(impact, surface_by_id)
        if (
            (impact.get("disposition") == "TEST_CHANGE" or impact.get("impact_kind") == "TEST_CHANGE")
            and (kind == "TEST" or not surface_by_id)
        ):
            return True
    return False


def _verified_owner_names(impact, challenge, evidence_by_id, surface_by_id=None):
    surface_by_id = surface_by_id or {}
    refs = list(impact.get("repository_evidence_ids", []) or []) + list(
        challenge.get("repository_evidence_ids", []) or []
    )
    names = set()
    for evidence_id in refs:
        item = evidence_by_id.get(str(evidence_id), {})
        if item.get("category") not in {"CURRENT_OWNER", "CURRENT_STATE_OWNER"}:
            continue
        symbol = str(item.get("symbol", ""))
        if symbol:
            names.add(symbol.split(".", 1)[0])
    surface = surface_by_id.get(str(impact.get("surface_id")), {})
    if surface.get("kind") == "OWNER" and surface.get("symbol"):
        names.add(str(surface.get("symbol")).split(".", 1)[0])
    return names


def _owner_conflicts_with_verified_owner(impact, challenge, evidence_by_id, surface_by_id=None):
    verified = _verified_owner_names(impact, challenge, evidence_by_id, surface_by_id)
    if not verified:
        return False
    surface_by_id = surface_by_id or {}
    surface = surface_by_id.get(str(impact.get("surface_id")), {})
    proposed = (
        impact.get("model_existing_owner")
        or impact.get("existing_owner")
        or impact.get("component")
    )
    proposed_base = str(proposed or "").split(".", 1)[0].strip()
    if proposed_base and proposed_base not in verified:
        # Canonical OWNER identity is already verified; do not treat its
        # component label as a conflict merely because the challenge cites a
        # broader owner fact.
        if not (surface.get("kind") == "OWNER" and proposed_base == str(surface.get("symbol", "")).split(".", 1)[0]):
            return True
    text = _impact_text(impact)
    explicit_names = {
        str(item.get("symbol", "")).split(".", 1)[0]
        for item in evidence_by_id.values()
        if item.get("category") in {"CURRENT_OWNER", "CURRENT_STATE_OWNER"}
        and item.get("symbol")
        and str(item.get("symbol")).split(".", 1)[0] in text
    }
    return bool(explicit_names - verified)


def _challenge_reference_status(challenge, impacts, req_by_id, evidence_by_id,
                                surface_registry=None):
    surface_by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    impact_ids = {str(item) for item in challenge.get("impact_ids", [])}
    requirement_ids = {str(item) for item in challenge.get("requirement_ids", [])}
    evidence_ids = {str(item) for item in challenge.get("repository_evidence_ids", [])}
    if any(item not in impacts for item in impact_ids):
        return False, "unknown impact reference"
    if any(item not in req_by_id for item in requirement_ids):
        return False, "unknown requirement reference"
    if any(item not in evidence_by_id for item in evidence_ids):
        return False, "unknown repository evidence reference"
    if surface_registry:
        surface_ids = {str(item) for item in challenge.get("surface_ids", [])}
        if any(item not in surface_by_id for item in surface_ids):
            return False, "unknown canonical surface reference"
        impact_surfaces = {
            str(impacts[item].get("surface_id")) for item in impact_ids if item in impacts
        }
        if surface_ids and impact_surfaces and not surface_ids.issubset(impact_surfaces):
            return False, "challenge surface does not match impact surface"
    return True, "valid canonical references"


def evaluate_challenge_applicability(challenge, impact_map, requirements, evidence,
                                     surface_registry=None, obligation_ledger=None):
    """Classify a validated challenge against the responsibility it targets.

    Reference validity and semantic applicability are intentionally separate.
    A valid, evidence-grounded criticism can therefore remain audit evidence
    while its effect is suppressed when the target does not make the claim
    that the challenge type attacks.
    """
    value = impact_map if isinstance(impact_map, dict) else {}
    impacts = {
        str(item.get("impact_id")): item
        for item in list(value.get("impacts", []) or [])
        if isinstance(item, dict) and item.get("impact_id")
    }
    req_by_id = {
        item["requirement_id"]: item for item in active_requirements(requirements)
    }
    evidence_by_id = {
        item["evidence_id"]: item
        for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    }
    references_valid, reference_reason = _challenge_reference_status(
        challenge, impacts, req_by_id, evidence_by_id, surface_registry,
    )
    if not references_valid:
        return {
            "applicable": False,
            "status": "REJECTED",
            "reason": reference_reason,
            "reference_status": "REJECTED",
        }
    surface_by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    impact_refs = [impacts[item] for item in challenge.get("impact_ids", []) if item in impacts]
    req_refs = [req_by_id[item] for item in challenge.get("requirement_ids", []) if item in req_by_id]
    req_types = _challenge_requirement_types(challenge, req_by_id, obligation_ledger)
    # Never trust a cached coverage projection while classifying a challenge;
    # applicability is a final-state semantic question, not an ID-presence
    # shortcut.
    semantic = evaluate_requirement_obligations(
        {"impacts": list(impacts.values())}, requirements, evidence,
        surface_registry, obligation_ledger,
    )
    semantic_by_id = {
        str(item.get("requirement_id")): item
        for item in semantic.get("requirements", [])
    }
    challenge_type = challenge.get("challenge_type")
    applicable = False
    reason = "challenge type is not applicable to the cited responsibility"

    if challenge_type == "UNSUPPORTED_NECESSITY":
        applicable = any(_impact_claims_mutation(item) for item in impact_refs)
        reason = (
            "target claims mutation necessity"
            if applicable else
            "target is non-mutating; unsupported mutation necessity cannot demote it"
        )
    elif challenge_type == "WRONG_OWNER":
        applicable = any(
            _impact_claims_mutation(item)
            and _owner_conflicts_with_verified_owner(item, challenge, evidence_by_id, surface_by_id)
            for item in impact_refs
        )
        reason = "mutation responsibility conflicts with verified owner" if applicable else reason
    elif challenge_type == "DUPLICATE_OWNERSHIP_RISK":
        applicable = any(
            _impact_implies_duplicate_owner(item)
            and bool(_verified_owner_names(item, challenge, evidence_by_id, surface_by_id))
            for item in impact_refs
        )
        reason = "responsibility implies a second owner or state owner" if applicable else reason
    elif challenge_type == "INTERFACE_REUSE_MISSED":
        for item in impact_refs:
            surface = surface_by_id.get(str(item.get("surface_id")), {})
            interfaces = [
                known for known in surface_by_id.values()
                if known.get("kind") == "INTERFACE"
                and (
                    known.get("owner_surface_id") == surface.get("surface_id")
                    or known.get("surface_id") in challenge.get("surface_ids", [])
                )
            ]
            relevant_evidence_ids = set(str(value) for value in (
                list(item.get("repository_evidence_ids", []) or [])
                + list(challenge.get("repository_evidence_ids", []) or [])
            ))
            verified_interface = any(
                evidence_by_id.get(evidence_id, {}).get("category") == "CURRENT_INTERFACE"
                for evidence_id in relevant_evidence_ids
            )
            present_ids = set(str(value) for value in item.get("interfaces_to_reuse", []))
            present_ids.update(str(value) for value in item.get("interface_surface_ids", []))
            present_names = set(str(value) for value in item.get("existing_interfaces_to_reuse", []))
            known_names = {str(value.get("symbol")) for value in interfaces if value.get("symbol")}
            if (interfaces or verified_interface) and not (present_ids or present_names.intersection(known_names)):
                applicable = True
                break
        reason = "verified reusable interface is absent" if applicable else reason
    elif challenge_type == "TEST_GAP":
        has_test_obligation = "TEST" in req_types or (
            "BEHAVIOR_CHANGE" in req_types
            and any(item.get("category") == "CURRENT_TEST" for item in evidence_by_id.values())
        )
        applicable = has_test_obligation and not _test_responsibility_exists(
            impacts.values(), challenge.get("requirement_ids", []), surface_by_id,
        )
        reason = "test obligation lacks a valid TEST responsibility" if applicable else reason
    elif challenge_type == "REQUIREMENT_GAP":
        applicable = any(
            semantic_by_id.get(str(item), {}).get("state") != "COVERED"
            for item in challenge.get("requirement_ids", [])
        )
        reason = "obligation-aware semantic coverage is missing" if applicable else reason
    elif challenge_type == "PRESERVATION_RISK":
        applicable = any(
            "PRESERVATION" in req_types
            and (
                _impact_claims_mutation(item)
                or _impact_surface_kind(item, surface_by_id) == "PERSISTENCE"
            )
            and not (item.get("local_preservation_constraints") or item.get("preserve"))
            for item in impact_refs
        )
        reason = "mutation threatens an uncovered preservation obligation" if applicable else reason
    elif challenge_type == "UNRELATED_CHANGE":
        requirement_terms = _domain_tokens(" ".join(item.get("text", "") for item in req_refs))
        impact_terms = _domain_tokens(" ".join(_impact_text(item) for item in impact_refs))
        evidence_terms = _domain_tokens(" ".join(
            str(item.get(key, "")) for item in evidence_by_id.values()
            for key in ("fact", "path", "symbol")
            if str(item.get("evidence_id")) in set(challenge.get("repository_evidence_ids", []))
        ))
        applicable = bool(impact_refs and req_refs) and any(
            _impact_claims_mutation(item) for item in impact_refs
        ) and not (requirement_terms & impact_terms) and not (requirement_terms & evidence_terms)
        reason = "mutation has no semantic relationship to cited requirements" if applicable else reason
    elif challenge_type == "MISSING_IMPACT":
        applicable = any(
            semantic_by_id.get(str(item), {}).get("state") != "COVERED"
            and not any(
                str(item) in {str(value) for value in impact.get("requirement_ids", [])}
                for impact in impacts.values()
            )
            for item in challenge.get("requirement_ids", [])
        )
        reason = "semantic obligation has no responsible impact" if applicable else reason
    elif challenge_type == "DEPENDENCY_GAP":
        dependency_evidence = {
            str(item.get("evidence_id")) for item in evidence_by_id.values()
            if item.get("category") == "CURRENT_DEPENDENCY"
            and str(item.get("evidence_id")) in set(challenge.get("repository_evidence_ids", []))
        }
        represented = any(
            impact.get("dependencies")
            or impact.get("integration_verification")
            for impact in impact_refs
        ) or bool(value.get("integration_verification"))
        applicable = bool(dependency_evidence) and not represented
        reason = "verified dependency is absent from the responsibility" if applicable else reason
    else:
        applicable = bool(impact_refs or req_refs)
        reason = "valid responsibility reference" if applicable else reason
    return {
        "applicable": bool(applicable),
        "status": "VALIDATED_APPLICABLE" if applicable else "VALIDATED_NON_APPLICABLE",
        "reason": reason,
        "reference_status": "VALID_REFERENCES",
    }


validate_challenge_applicability = evaluate_challenge_applicability


def _challenge_relationship_supported(challenge, impacts, req_by_id, evidence_by_id,
                                      surface_registry=None):
    challenge_type = challenge.get("challenge_type")
    impact_refs = [impacts[item] for item in challenge.get("impact_ids", []) if item in impacts]
    requirement_refs = [req_by_id[item] for item in challenge.get("requirement_ids", []) if item in req_by_id]
    evidence_refs = [
        evidence_by_id[item] for item in challenge.get("repository_evidence_ids", []) if item in evidence_by_id
    ]
    if challenge_type in {"MISSING_IMPACT", "REQUIREMENT_GAP", "TEST_GAP"}:
        if not requirement_refs:
            return False
    elif not impact_refs:
        return False
    if challenge_type in {
        "WRONG_OWNER", "DUPLICATE_OWNERSHIP_RISK", "PRESERVATION_RISK",
        "INTERFACE_REUSE_MISSED", "TEST_GAP", "DEPENDENCY_GAP",
    } and not evidence_refs:
        return False
    if challenge_type in {"WRONG_OWNER", "DUPLICATE_OWNERSHIP_RISK"}:
        return any(item.get("category") in {"CURRENT_OWNER", "CURRENT_STATE_OWNER"} for item in evidence_refs)
    if challenge_type == "INTERFACE_REUSE_MISSED":
        return any(item.get("category") == "CURRENT_INTERFACE" for item in evidence_refs)
    if challenge_type == "TEST_GAP":
        return (
            any(item.get("category") == "CURRENT_TEST" for item in evidence_refs)
            and any(_TEST_RE.search(item["text"]) for item in requirement_refs)
        )
    if challenge_type == "PRESERVATION_RISK":
        return any(_PRESERVE_RE.search(item["text"]) for item in requirement_refs)
    if challenge_type == "UNSUPPORTED_NECESSITY":
        if not impact_refs:
            return False
        # Relationship validation only proves that the criticism cites an
        # existing responsibility.  Whether unsupported necessity applies is
        # a separate semantic question handled below; otherwise a valid
        # challenge against INTERFACE_REUSE would be rejected before it could
        # be retained as suppressed audit evidence.
        return any(
            _impact_claims_mutation(item)
            or item.get("disposition") in {
                "INTERFACE_REUSE", "PRESERVATION_ONLY", "VERIFY_ONLY",
                "TEST_REFERENCE", "TEST_CHANGE",
            }
            for item in impact_refs
        )
    if challenge_type == "REQUIREMENT_GAP":
        semantic = evaluate_requirement_obligations(
            {"impacts": list(impacts.values())}, requirement_refs,
            list(evidence_by_id.values()), surface_registry,
        )
        return any(item.get("state") == "UNCOVERED" for item in semantic["requirements"])
    if challenge_type == "UNRELATED_CHANGE":
        if not impact_refs or not requirement_refs or not evidence_refs:
            return False
        requirement_terms = _tokens(" ".join(item["text"] for item in requirement_refs))
        impact_terms = _tokens(" ".join(_impact_text(item) for item in impact_refs))
        evidence_terms = _tokens(" ".join(
            str(item.get(key, "")) for item in evidence_refs for key in ("fact", "path", "symbol")
        ))
        return not (requirement_terms & impact_terms) and not (requirement_terms & evidence_terms)
    if challenge_type == "DEPENDENCY_GAP":
        return any(item.get("category") == "CURRENT_DEPENDENCY" for item in evidence_refs)
    if challenge_type == "MISSING_IMPACT":
        covered_evidence = {
            str(value) for item in impacts.values() for value in item.get("repository_evidence_ids", [])
        }
        return any(item["evidence_id"] not in covered_evidence for item in evidence_refs)
    return True


def validate_challenges(challenges, impact_map, requirements, evidence, surface_registry=None):
    impacts = {
        str(item.get("impact_id")): item for item in list((impact_map or {}).get("impacts", []) or [])
        if isinstance(item, dict) and item.get("impact_id")
    }
    req_by_id = {item["requirement_id"]: item for item in active_requirements(requirements)}
    evidence_by_id = {item["evidence_id"]: item for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)}
    accepted, rejected = [], []
    applicable, non_applicable = [], []
    seen = set()
    for item in list(challenges or [])[:MAX_CHALLENGES]:
        challenge = copy.deepcopy(item)
        challenge_id = str(challenge.get("challenge_id", ""))
        errors = []
        if not challenge_id or challenge_id in seen:
            errors.append("challenge ID must be present and unique")
        seen.add(challenge_id)
        if challenge.get("challenge_type") not in CHALLENGE_TYPES:
            errors.append("unknown challenge type")
        unknown_impacts = set(challenge.get("impact_ids", [])) - set(impacts)
        unknown_requirements = set(challenge.get("requirement_ids", [])) - set(req_by_id)
        unknown_evidence = set(challenge.get("repository_evidence_ids", [])) - set(evidence_by_id)
        if unknown_impacts:
            errors.append("unknown impact reference")
        if unknown_requirements:
            errors.append("unknown requirement reference")
        if unknown_evidence:
            errors.append("unknown or stale repository evidence reference")
        if surface_registry:
            by_surface = canonical_surface_by_id(surface_registry)
            surface_refs = {str(item) for item in challenge.get("surface_ids", [])}
            impact_surfaces = {
                str(impacts[item].get("surface_id"))
                for item in challenge.get("impact_ids", []) if item in impacts
            }
            if surface_refs - set(by_surface):
                errors.append("unknown canonical surface reference")
            if surface_refs and impact_surfaces and not surface_refs.issubset(impact_surfaces):
                errors.append("challenge surface does not match impact surface")
            for impact_id in challenge.get("impact_ids", []):
                impact = impacts.get(impact_id)
                surface = by_surface.get(str(impact.get("surface_id"))) if impact else None
                if surface and challenge.get("repository_evidence_ids"):
                    supported_evidence = set(str(item) for item in surface.get("evidence_ids", []))
                    supported_evidence.update(
                        str(evidence_id)
                        for interface in by_surface.values()
                        if interface.get("kind") == "INTERFACE"
                        and interface.get("owner_surface_id") == surface.get("surface_id")
                        for evidence_id in interface.get("evidence_ids", [])
                    )
                    if not set(str(item) for item in challenge.get("repository_evidence_ids", [])).intersection(supported_evidence):
                        errors.append("challenge evidence does not support the impacted surface")
        if not errors and challenge.get("source") == "MODEL":
            relationship_text = " ".join(
                [_impact_text(impacts[item]) for item in challenge.get("impact_ids", []) if item in impacts]
                + [req_by_id[item]["text"] for item in challenge.get("requirement_ids", []) if item in req_by_id]
                + [
                    str(evidence_by_id[item].get(key, ""))
                    for item in challenge.get("repository_evidence_ids", []) if item in evidence_by_id
                    for key in ("fact", "path", "symbol")
                ]
            )
            if challenge.get("claim") and not (_tokens(challenge.get("claim")) & _tokens(relationship_text)):
                errors.append("model criticism is not semantically grounded in cited facts")
        if not errors and not _challenge_relationship_supported(
            challenge, impacts, req_by_id, evidence_by_id, surface_registry,
        ):
            errors.append("claimed relationship is not supported by the cited evidence")
        if errors:
            challenge["validation_status"] = "REJECTED"
            challenge["validation_errors"] = errors
            challenge["reference_status"] = "REJECTED"
            challenge["applicability_status"] = "REJECTED"
            challenge["applicability_reason"] = "; ".join(errors[:2])
            challenge["effect_status"] = "NOT_APPLICABLE"
            challenge["lifecycle_state"] = "REJECTED"
            challenge["resolution_status"] = "REJECTED"
            rejected.append(challenge)
        else:
            applicability = evaluate_challenge_applicability(
                challenge, {"impacts": list(impacts.values())}, requirements, evidence,
                surface_registry=surface_registry,
            )
            challenge["validation_status"] = "VALIDATED"
            challenge["reference_status"] = applicability.get(
                "reference_status", "VALID_REFERENCES",
            )
            challenge["applicability_status"] = applicability.get(
                "status", "VALIDATED_NON_APPLICABLE",
            )
            challenge["applicability_reason"] = applicability.get("reason", "")
            challenge["effect_status"] = (
                "PENDING" if applicability.get("applicable") else "NOT_APPLICABLE"
            )
            challenge["lifecycle_state"] = "OPEN"
            challenge["resolution_status"] = "OPEN"
            accepted.append(challenge)
            (applicable if applicability.get("applicable") else non_applicable).append(challenge)
    return {
        "validated": accepted,
        "rejected": rejected,
        "applicable": applicable,
        "non_applicable": non_applicable,
    }


def merge_challenges(model_challenges, deterministic):
    result = []
    seen = set()
    for item in list(model_challenges or []) + list(deterministic or []):
        key = (
            item.get("challenge_type"), tuple(sorted(item.get("impact_ids", []))),
            tuple(sorted(item.get("requirement_ids", []))),
            tuple(sorted(item.get("repository_evidence_ids", []))),
        )
        if key in seen:
            continue
        seen.add(key)
        value = copy.deepcopy(item)
        value["challenge_id"] = f"CH-{len(result) + 1:03d}"
        result.append(value)
        if len(result) >= MAX_CHALLENGES:
            break
    return result


def _evidence_impacts_for_gap(challenge, requirements, evidence, start_index,
                              surface_registry=None, impact_seeds=None):
    req_by_id = {item["requirement_id"]: item for item in active_requirements(requirements)}
    facts = {
        item["evidence_id"]: item for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    }
    selected = [facts[item] for item in challenge.get("repository_evidence_ids", []) if item in facts]
    if surface_registry:
        by_surface = canonical_surface_by_id(surface_registry)
        selected_surfaces = [
            by_surface[item] for item in challenge.get("surface_ids", []) if item in by_surface
        ]
        if selected_surfaces:
            selected = [
                facts[evidence_id] for surface in selected_surfaces
                for evidence_id in surface.get("evidence_ids", []) if evidence_id in facts
            ]
    grouped = {}
    for item in selected:
        grouped.setdefault(item.get("path") or item.get("evidence_id"), []).append(item)
    impacts = []
    seed_by_surface = {
        str(item.get("surface_id")): item for item in list(impact_seeds or [])
        if isinstance(item, dict) and item.get("surface_id")
    }
    for path, records in grouped.items():
        categories = {item.get("category") for item in records}
        kind = "TEST_CHANGE" if "CURRENT_TEST" in categories else "INTEGRATION_CHANGE"
        symbols = _bounded_strings([item.get("symbol") for item in records], 6, 160)
        component = next((item.split(".", 1)[0] for item in symbols if item), path)
        requirement_ids = [item for item in challenge.get("requirement_ids", []) if item in req_by_id]
        if surface_registry:
            surface = next((
                item for item in surface_registry.get("surfaces", [])
                if _normal_path(item.get("path")) == _normal_path(path)
            ), None)
            if not surface:
                continue
            seed = seed_by_surface.get(str(surface.get("surface_id")))
            impacts.append({
                "impact_id": normalize_impact_id(seed.get("impact_id")) if seed else f"IMP-{start_index + len(impacts):03d}",
                "surface_id": surface.get("surface_id"),
                "disposition": "TEST_CHANGE" if kind == "TEST_CHANGE" else "MUST_CHANGE",
                "requirement_ids": requirement_ids,
                "repository_evidence_ids": list(surface.get("evidence_ids", [])),
                "interfaces_to_reuse": [
                    item.get("surface_id") for item in surface_registry.get("surfaces", [])
                    if item.get("kind") == "INTERFACE"
                    and _normal_path(item.get("path")) == _normal_path(surface.get("path"))
                ][:6],
                "action": challenge.get("proposed_resolution", "Cover the validated missing responsibility."),
                "verification": [req_by_id[item]["text"] for item in requirement_ids],
                "preserve": [],
            })
            continue
        impacts.append({
            "impact_id": f"IMP-{start_index + len(impacts):03d}",
            "component": component,
            "path": path,
            "symbols": symbols,
            "impact_kind": kind,
            "requirement_ids": requirement_ids,
            "repository_evidence_ids": [item["evidence_id"] for item in records],
            "reason": challenge.get("claim", "A validated gap requires explicit responsibility."),
            "existing_owner": component if kind != "TEST_CHANGE" else "",
            "existing_interfaces_to_reuse": _bounded_strings([
                item.get("symbol") for item in records if item.get("category") == "CURRENT_INTERFACE"
            ], 6, 180),
            "preserve": [],
            "candidate_change": challenge.get("proposed_resolution", "Cover the validated missing responsibility."),
            "local_verification": [req_by_id[item]["text"] for item in requirement_ids],
            "necessity_status": "CANDIDATE",
        })
    return impacts


def _unsupported_necessity_defect_exists(target, evidence_by_id, surface_by_id=None):
    linked = [
        evidence_by_id[item] for item in target.get("repository_evidence_ids", [])
        if item in evidence_by_id
    ]
    return _impact_claims_mutation(target) and (
        not target.get("requirement_ids")
        or (
            not target.get("repository_evidence_ids")
            and not target.get("new_surface_proposal_ids")
        )
        or _impact_surface_kind(target, surface_by_id) == "PERSISTENCE"
        or any(item.get("category") == "CURRENT_PERSISTENCE" for item in linked)
    )


def _challenge_defect_exists(challenge, final_source, target_source, requirements,
                             evidence, surface_registry=None, obligation_ledger=None):
    """Evaluate whether a challenge's semantic defect survives final closure."""
    value = target_source if isinstance(target_source, dict) else {}
    impacts = {
        str(item.get("impact_id")): item
        for item in list(value.get("impacts", []) or [])
        if isinstance(item, dict) and item.get("impact_id")
    }
    targets = [
        impacts[item] for item in challenge.get("impact_ids", []) if item in impacts
    ]
    surface_by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    evidence_by_id = {
        item["evidence_id"]: item
        for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    }
    semantic = evaluate_requirement_obligations(
        final_source if isinstance(final_source, dict) else value,
        requirements, evidence, surface_registry, obligation_ledger,
    )
    semantic_by_id = {
        str(item.get("requirement_id")): item
        for item in semantic.get("requirements", [])
    }
    challenge_type = challenge.get("challenge_type")
    if challenge_type in {"REQUIREMENT_GAP", "MISSING_IMPACT", "DEPENDENCY_GAP"}:
        return any(
            semantic_by_id.get(str(requirement_id), {}).get("state") != "COVERED"
            for requirement_id in challenge.get("requirement_ids", [])
        )
    if challenge_type == "TEST_GAP":
        return any(
            any(
                item.get("obligation_type") == "TEST" and item.get("state") != "COVERED"
                for item in semantic_by_id.get(str(requirement_id), {}).get("obligations", [])
            )
            for requirement_id in challenge.get("requirement_ids", [])
        )
    if challenge_type == "INTERFACE_REUSE_MISSED":
        return any(not (
            item.get("interfaces_to_reuse") or item.get("interface_surface_ids")
            or item.get("existing_interfaces_to_reuse")
        ) for item in targets)
    if challenge_type == "PRESERVATION_RISK":
        return any(not (
            item.get("preserve") or item.get("local_preservation_constraints")
            or item.get("preservation_constraints")
        ) for item in targets)
    if challenge_type == "UNSUPPORTED_NECESSITY":
        return any(_unsupported_necessity_defect_exists(item, evidence_by_id, surface_by_id) for item in targets)
    if challenge_type in {"WRONG_OWNER", "DUPLICATE_OWNERSHIP_RISK"}:
        applicability = evaluate_challenge_applicability(
            challenge, value, requirements, evidence,
            surface_registry=surface_registry, obligation_ledger=obligation_ledger,
        )
        return bool(applicability.get("applicable"))
    if challenge_type == "UNRELATED_CHANGE":
        req_by_id = {item["requirement_id"]: item for item in active_requirements(requirements)}
        req_terms = _domain_tokens(" ".join(
            req_by_id[item]["text"] for item in challenge.get("requirement_ids", [])
            if item in req_by_id
        ))
        return any(
            _impact_claims_mutation(item)
            and req_terms
            and not (req_terms & _domain_tokens(_impact_text(item)))
            for item in targets
        )
    return not bool(challenge.get("effect_status") in {"APPLIED", "SUPPRESSED"})


def re_evaluate_challenge_lifecycle(challenges, final_source, requirements, evidence,
                                    surface_registry=None, obligation_ledger=None,
                                    impact_map=None, closure_actions=None):
    """Recompute challenge state from final responsibilities, not branch history."""
    final_source = final_source if isinstance(final_source, dict) else {}
    target_source = impact_map if isinstance(impact_map, dict) else final_source
    resolved, unresolved, lifecycle = [], [], []
    closure_actions = list(closure_actions or [])
    for item in list(challenges or [])[:MAX_CHALLENGES]:
        challenge = copy.deepcopy(item)
        initial_status = challenge.get("applicability_status")
        if initial_status is None:
            initial = evaluate_challenge_applicability(
                challenge, target_source, requirements, evidence,
                surface_registry=surface_registry, obligation_ledger=obligation_ledger,
            )
            initial_status = initial.get("status")
            challenge["applicability_status"] = initial_status
            challenge["applicability_reason"] = initial.get("reason", "")
        final_applicability = evaluate_challenge_applicability(
            challenge, target_source, requirements, evidence,
            surface_registry=surface_registry, obligation_ledger=obligation_ledger,
        )
        challenge["final_applicability_status"] = final_applicability.get("status")
        challenge["final_applicability_reason"] = final_applicability.get("reason", "")
        defect = False if initial_status == "VALIDATED_NON_APPLICABLE" else _challenge_defect_exists(
            challenge, final_source, target_source, requirements, evidence,
            surface_registry=surface_registry, obligation_ledger=obligation_ledger,
        )
        if defect:
            state = "OPEN"
        elif challenge.get("effect_status") == "APPLIED":
            state = "RESOLVED"
        elif initial_status == "VALIDATED_NON_APPLICABLE":
            state = "SUPERSEDED"
        elif any(
            str(requirement_id) in {
                str(value) for value in action.get("requirement_ids", [])
            }
            for action in closure_actions
            for requirement_id in challenge.get("requirement_ids", [])
        ):
            state = "SUPERSEDED"
        else:
            state = "SUPERSEDED"
        challenge["final_defect_exists"] = bool(defect)
        challenge["lifecycle_state"] = state
        challenge["resolution_status"] = state
        challenge["post_reconciliation_evaluation"] = True
        lifecycle.append(challenge)
        (unresolved if state == "OPEN" else resolved).append(challenge)
    return lifecycle, resolved, unresolved


def reconcile_impact_map(impact_map, validated_challenges, requirements, evidence,
                         surface_registry=None, impact_seeds=None,
                         obligation_ledger=None, task_goal=None, task_brain=None,
                         obligation_aware=None):
    """Apply one bounded deterministic revision while conserving obligations."""
    revised = copy.deepcopy(impact_map if isinstance(impact_map, dict) else {})
    impacts = list(revised.get("impacts", []) or [])
    by_id = {str(item.get("impact_id")): item for item in impacts}
    evidence_by_id = {
        item["evidence_id"]: item for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    }
    req_by_id = {item["requirement_id"]: item for item in active_requirements(requirements)}
    surface_by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    supplied_ledger = obligation_ledger or revised.get("requirement_obligation_ledger")
    if obligation_aware is None:
        obligation_aware = _is_obligation_aware_artifact(revised, supplied_ledger)
    obligation_ledger = supplied_ledger or build_requirement_obligation_ledger(requirements)
    challenge_records = []
    for item in list(validated_challenges or [])[:MAX_CHALLENGES]:
        challenge = copy.deepcopy(item)
        if challenge.get("applicability_status") not in {
            "VALIDATED_APPLICABLE", "VALIDATED_NON_APPLICABLE",
        }:
            applicability = evaluate_challenge_applicability(
                challenge, {"impacts": impacts}, requirements, evidence,
                surface_registry=surface_registry,
                obligation_ledger=obligation_ledger,
            )
            challenge["reference_status"] = applicability.get("reference_status")
            challenge["applicability_status"] = applicability.get("status")
            challenge["applicability_reason"] = applicability.get("reason")
        challenge_records.append(challenge)
    application_by_id = {}
    deferred_effects = []
    for challenge in challenge_records:
        challenge_type = challenge.get("challenge_type")
        targets = [by_id[item] for item in challenge.get("impact_ids", []) if item in by_id]
        applied = False
        challenge_id = str(challenge.get("challenge_id"))
        if challenge.get("applicability_status") != "VALIDATED_APPLICABLE":
            challenge["effect_status"] = "SUPPRESSED"
            application_by_id[challenge_id] = "SUPPRESSED"
            continue
        if challenge_type in {"UNSUPPORTED_NECESSITY", "UNRELATED_CHANGE"}:
            for target in targets:
                if challenge_type == "UNRELATED_CHANGE" and target.get("disposition") == "PRESERVATION_ONLY":
                    applied = True
                    continue
                linked = [
                    evidence_by_id[item] for item in target.get("repository_evidence_ids", [])
                    if item in evidence_by_id
                ]
                preservation = (
                    target.get("impact_kind") == "PRESERVATION_ONLY"
                    or any(item.get("category") == "CURRENT_PERSISTENCE" for item in linked)
                )
                if preservation and challenge_type == "UNSUPPORTED_NECESSITY":
                    target["impact_kind"] = "PRESERVATION_ONLY"
                    target["disposition"] = "PRESERVATION_ONLY"
                    target["necessity_status"] = "PRESERVATION_ONLY"
                    target["candidate_change"] = "No mutation planned; retain this verified preservation surface."
                    target["action"] = target["candidate_change"]
                    target["preserve"] = _bounded_strings(
                        list(target.get("preserve", [])) + [
                            req_by_id[item]["text"] for item in challenge.get("requirement_ids", [])
                            if item in req_by_id and _PRESERVE_RE.search(req_by_id[item]["text"])
                        ],
                        6, 300,
                    )
                    applied = True
                else:
                    # Destructive demotion is deliberately deferred until
                    # behavior/preservation/test closure has inspected every
                    # canonical anchor.  A later pass can still demote a
                    # genuinely unsupported mutation.
                    deferred_effects.append((challenge, str(target.get("impact_id"))))
                    challenge["effect_status"] = "DEFERRED"
        elif challenge_type in {"WRONG_OWNER", "DUPLICATE_OWNERSHIP_RISK"}:
            for target in targets:
                owner_facts = [
                    evidence_by_id[item] for item in target.get("repository_evidence_ids", [])
                    if item in evidence_by_id
                    and evidence_by_id[item].get("category") in {"CURRENT_OWNER", "CURRENT_STATE_OWNER"}
                ]
                owner = next((item.get("symbol", "").split(".", 1)[0] for item in owner_facts if item.get("symbol")), "")
                if owner:
                    target["existing_owner"] = owner
                    if surface_registry:
                        target_surface = surface_by_id.get(str(target.get("surface_id")))
                        if target_surface:
                            target["existing_owner"] = target_surface.get("symbol", owner)
                    target["candidate_change"] = _compact(
                        challenge.get("proposed_resolution")
                        or "Use the verified owner; do not introduce duplicate state ownership.",
                    )
                    target["action"] = target["candidate_change"]
                    target["reason"] = target["candidate_change"]
                    target["preserve"] = _bounded_strings(
                        list(target.get("preserve", [])) + [f"authoritative state ownership remains with {owner}"],
                        6, 300,
                    )
                    applied = True
        elif challenge_type == "INTERFACE_REUSE_MISSED":
            challenge_evidence_ids = list(challenge.get("repository_evidence_ids", []))
            for target in targets:
                interfaces = [
                    evidence_by_id[item].get("symbol")
                    for item in list(target.get("repository_evidence_ids", [])) + challenge_evidence_ids
                    if item in evidence_by_id and evidence_by_id[item].get("category") == "CURRENT_INTERFACE"
                ]
                if interfaces:
                    target["existing_interfaces_to_reuse"] = _bounded_strings(
                        list(target.get("existing_interfaces_to_reuse", [])) + interfaces, 6, 180,
                    )
                    if surface_registry:
                        interface_ids = [
                            item.get("surface_id") for item in surface_by_id.values()
                            if item.get("kind") == "INTERFACE"
                            and str(item.get("symbol")) in interfaces
                        ]
                        target["interfaces_to_reuse"] = _bounded_ids(
                            list(target.get("interfaces_to_reuse", [])) + interface_ids, 6,
                        )
                        target["interface_surface_ids"] = list(target["interfaces_to_reuse"])
                    target["candidate_change"] = _compact(
                        challenge.get("proposed_resolution") or "Reuse the verified current interface.",
                    )
                    target["action"] = target["candidate_change"]
                    applied = True
        elif challenge_type in {"TEST_GAP", "MISSING_IMPACT", "REQUIREMENT_GAP", "DEPENDENCY_GAP"}:
            additions = _evidence_impacts_for_gap(
                challenge, requirements, evidence, len(impacts) + 1,
                surface_registry=surface_registry, impact_seeds=impact_seeds,
            )
            for addition in additions:
                if any(
                    str(existing.get("surface_id")) == str(addition.get("surface_id"))
                    for existing in impacts
                    if isinstance(existing, dict)
                ):
                    continue
                if len(impacts) >= MAX_IMPACT_ENTRIES:
                    break
                impacts.append(addition)
                by_id[addition["impact_id"]] = addition
                applied = True
        elif challenge_type == "PRESERVATION_RISK":
            for target in targets:
                target["preserve"] = _bounded_strings(
                    list(target.get("preserve", [])) + [challenge.get("proposed_resolution")], 6, 300,
                )
                applied = True
        if applied:
            challenge["effect_status"] = "APPLIED"
            application_by_id[challenge_id] = "APPLIED"
        elif challenge.get("effect_status") != "DEFERRED":
            challenge["effect_status"] = "PENDING"
            application_by_id[challenge_id] = "PENDING"
    revised["impacts"] = impacts[:MAX_IMPACT_ENTRIES]
    revised["challenge_rounds"] = 1
    revised["revision_rounds"] = 1 if challenge_records else 0
    if task_goal is not None:
        # The caller supplies the already canonical Source Contract goal.
        # Preserve it exactly; prompt-file whitespace must not become plan
        # authority.
        revised["task_goal"] = str(task_goal)
    revised = _apply_obligation_constraints(
        revised, requirements, surface_registry, impact_seeds, obligation_ledger,
    )
    revised, synthesized_actions = _synthesize_obligation_impacts(
        revised, requirements, evidence, surface_registry, impact_seeds,
        obligation_ledger,
    )
    revised, closure_actions = close_behavior_obligation_gaps(
        revised, requirements, evidence, surface_registry, impact_seeds,
        obligation_ledger,
    )
    revised = _apply_obligation_constraints(
        revised, requirements, surface_registry, impact_seeds, obligation_ledger,
    )

    # Apply only those deferred destructive effects that still describe a
    # real final-state defect.  A canonical owner carrying a behavior duty is
    # conserved even when a weak criticism was initially aimed at its weaker
    # disposition.
    for challenge, target_id in deferred_effects:
        current_by_id = {
            str(item.get("impact_id")): item
            for item in revised.get("impacts", [])
            if isinstance(item, dict) and item.get("impact_id")
        }
        target = current_by_id.get(target_id)
        if target is None:
            continue
        challenge_id = str(challenge.get("challenge_id"))
        if challenge.get("challenge_type") == "UNSUPPORTED_NECESSITY":
            linked = [
                evidence_by_id[item] for item in target.get("repository_evidence_ids", [])
                if item in evidence_by_id
            ]
            behavior_link = any(
                "BEHAVIOR_CHANGE" in next(
                    (
                        record.get("obligation_types", [])
                        for record in _obligation_records(obligation_ledger)
                        if record.get("requirement_id") == str(requirement_id)
                    ),
                    [],
                )
                for requirement_id in target.get("requirement_ids", [])
            )
            still_unsupported = (
                _impact_claims_mutation(target)
                and not behavior_link
                and (
                    not target.get("requirement_ids")
                    or (
                        not target.get("repository_evidence_ids")
                        and not target.get("new_surface_proposal_ids")
                    )
                    or _impact_surface_kind(target, surface_by_id) == "PERSISTENCE"
                    or any(item.get("category") == "CURRENT_PERSISTENCE" for item in linked)
                )
            )
        else:
            requirement_terms = _domain_tokens(" ".join(
                req_by_id[item]["text"] for item in challenge.get("requirement_ids", [])
                if item in req_by_id
            ))
            impact_terms = _domain_tokens(_impact_text(target))
            still_unsupported = bool(requirement_terms) and not (
                requirement_terms & impact_terms
            ) and _impact_claims_mutation(target)
        if still_unsupported:
            target["disposition"] = "INSUFFICIENT_EVIDENCE"
            target["necessity_status"] = "INSUFFICIENT_EVIDENCE"
            target["impact_kind"] = "INTEGRATION_CHANGE"
            challenge["effect_status"] = "APPLIED"
            application_by_id[challenge_id] = "APPLIED"
        else:
            challenge["effect_status"] = "SUPPRESSED"
            application_by_id[challenge_id] = "SUPPRESSED"
    revised["impacts"] = list(revised.get("impacts", []) or [])[:MAX_IMPACT_ENTRIES]
    revised["obligation_impacts_synthesized"] = int(
        revised.get("obligation_impacts_synthesized", 0) or 0
    )
    revised["challenge_effects_applied"] = sum(
        value == "APPLIED" for value in application_by_id.values()
    )
    revised["challenge_effects_suppressed"] = sum(
        value == "SUPPRESSED" for value in application_by_id.values()
    )
    revised["impact_challenges_applicable"] = sum(
        item.get("applicability_status") == "VALIDATED_APPLICABLE"
        for item in challenge_records
    )
    revised["impact_challenges_non_applicable"] = sum(
        item.get("applicability_status") == "VALIDATED_NON_APPLICABLE"
        for item in challenge_records
    )
    normalized = normalize_impact_map(revised, authoritative=bool(surface_registry))
    if task_goal is not None:
        # normalize_impact_map intentionally compacts ordinary model text;
        # the Stage 3 authority passed by the Source Contract is different
        # and must survive byte-for-byte into the final plan/hash.
        normalized["task_goal"] = str(task_goal)
    semantic = evaluate_requirement_obligations(
        normalized, requirements, evidence, surface_registry, obligation_ledger,
    )
    normalized["requirement_obligation_ledger"] = copy.deepcopy(
        obligation_ledger if obligation_aware else
        _legacy_requirement_obligation_ledger(obligation_ledger)
    )
    normalized["semantic_obligation_coverage"] = copy.deepcopy(
        semantic if obligation_aware else _legacy_semantic_obligation_coverage(semantic)
    )
    normalized["deterministic_behavior_anchor_promotions"] = len(closure_actions)
    normalized["behavior_anchor_closure_actions"] = closure_actions
    obligation_metric_keys = {
        "PRESERVATION": "preservation_obligations_closed",
        "ARCHITECTURE_REUSE": "reuse_obligations_closed",
        "TEST": "test_obligations_closed",
        "PROHIBITION": "prohibition_obligations_closed",
    }
    for obligation_type, metric in obligation_metric_keys.items():
        normalized[metric] = sum(
            item.get("state") == "COVERED"
            for record in semantic.get("requirements", [])
            for item in record.get("obligations", [])
            if item.get("obligation_type") == obligation_type
        )
    lifecycle, resolved, unresolved = re_evaluate_challenge_lifecycle(
        challenge_records, normalized, requirements, evidence,
        surface_registry=surface_registry, obligation_ledger=obligation_ledger,
        impact_map=normalized, closure_actions=closure_actions + synthesized_actions,
    )
    normalized["challenge_lifecycle"] = lifecycle
    normalized["challenges_resolved_post_reconciliation"] = len(resolved)
    normalized["challenges_remaining_open"] = len(unresolved)
    return normalized, resolved, unresolved


def _requirement_change_required(requirement_ids, req_by_id):
    return any(_CHANGE_RE.search(req_by_id[item]["text"]) for item in requirement_ids if item in req_by_id)


def _surface_record(impact, surface_registry=None):
    surface = canonical_surface_by_id(surface_registry).get(
        str(impact.get("surface_id")),
    ) if surface_registry else None
    path = _normal_path((surface or impact).get("path"))
    symbol = (surface or impact).get("symbol")
    return {
        "surface_id": (surface or impact).get("surface_id") or impact.get("canonical_surface_id"),
        "canonical_surface_id": (surface or impact).get("surface_id") or impact.get("canonical_surface_id"),
        "kind": (surface or {}).get("kind") or impact.get("surface_kind"),
        "role": (surface or {}).get("role") or impact.get("surface_role"),
        "component": symbol or impact.get("component"),
        "path": path,
        "symbols": _bounded_strings(
            [symbol] if symbol else list(impact.get("symbols", [])), 6, 160,
        ),
        "requirement_ids": list(impact.get("requirement_ids", [])),
        "evidence_ids": list((surface or {}).get("evidence_ids", []) or impact.get("repository_evidence_ids", [])),
        "reason": impact.get("reason"),
        "preservation_constraints": _bounded_strings(
            list(impact.get("local_preservation_constraints", []) or [])
            + list(impact.get("preserve", []) or []), 8, 300,
        ),
        "prohibition_constraints": _bounded_strings(
            impact.get("prohibition_constraints"), 6, 320,
        ),
        "mutation_planned": False,
        "provenance": DERIVED_PLAN_DECISION,
    }


def derive_do_not_touch_surface_ids(impact_map, surface_registry=None):
    """Derive pure preservation surfaces and disjoint canonical paths."""
    impacts = list((impact_map or {}).get("impacts", []) or [])
    by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    mutation_ids = {
        str(item.get("surface_id")) for item in impacts
        if item.get("surface_id") and (
            item.get("necessity_status") == "MUST_CHANGE"
            or item.get("disposition") in {"MUST_CHANGE", "TEST_CHANGE"}
        )
    }
    mutation_paths = {
        _normal_path(by_id[item].get("path")) for item in mutation_ids if item in by_id
    }
    preservation_ids = set()
    for item in impacts:
        surface_id = str(item.get("surface_id") or "")
        is_preservation = (
            item.get("disposition") == "PRESERVATION_ONLY"
            or item.get("necessity_status") == "PRESERVATION_ONLY"
            or item.get("impact_kind") == "PRESERVATION_ONLY"
        )
        if not is_preservation or not surface_id or surface_id in mutation_ids:
            continue
        path = _normal_path(by_id.get(surface_id, item).get("path"))
        if path and path not in mutation_paths:
            preservation_ids.add(surface_id)
    records = [
        by_id[item] for item in sorted(preservation_ids)
        if item in by_id
    ]
    paths = _bounded_strings([item.get("path") for item in records], MAX_PLAN_NODES, 240)
    return {
        "surface_ids": sorted(preservation_ids),
        "paths": paths,
        "mutation_surface_ids": sorted(mutation_ids),
        "mutation_paths": sorted(mutation_paths),
    }


derive_do_not_touch = derive_do_not_touch_surface_ids


def _canonical_plan_payload(plan):
    value = copy.deepcopy(plan if isinstance(plan, dict) else {})
    value.pop("plan_id", None)
    value.pop("plan_hash", None)
    value.pop("approval", None)
    return value


def plan_content_hash(plan):
    payload = json.dumps(
        _canonical_plan_payload(plan), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def finalize_plan_identity(plan):
    value = copy.deepcopy(plan if isinstance(plan, dict) else {})
    value.pop("plan_id", None)
    value.pop("plan_hash", None)
    digest = plan_content_hash(value)
    value["plan_id"] = f"PLAN-{digest[:12].upper()}"
    value["plan_hash"] = digest
    return value


def _plan_challenge_record(challenge):
    """Keep final challenge state auditable without duplicating model prose."""
    value = challenge if isinstance(challenge, dict) else {}
    return {
        key: copy.deepcopy(value.get(key))
        for key in (
            "challenge_id", "challenge_type", "impact_ids", "requirement_ids",
            "blocking",
            "applicability_status", "effect_status", "lifecycle_state",
            "resolution_status",
        )
        if value.get(key) not in (None, "", [], {})
    }


compact_challenge_record = _plan_challenge_record


def _canonical_final_plan_challenge_summary(resolved, unresolved,
                                            reconciliation_hash=None):
    """Bind review outcome without copying the review packet into authority.

    The immutable challenge/reconciliation artifact remains the source of
    claims, evidence, and deterministic effects.  A canonical approval plan
    needs only the bounded outcome index and its identity; retaining one
    compact record per challenge makes final-plan size depend on model output
    cardinality even though those records are not execution authority.
    """
    resolved = [
        _plan_challenge_record(item)
        for item in list(resolved or [])[:MAX_CHALLENGES]
        if isinstance(item, dict)
    ]
    unresolved = [
        _plan_challenge_record(item)
        for item in list(unresolved or [])[:MAX_CHALLENGES]
        if isinstance(item, dict)
    ]

    def ids(values):
        return _canonical_final_plan_unique(
            item.get("challenge_id") for item in values
        )

    def ids_with_effect(values, effect):
        return _canonical_final_plan_unique(
            item.get("challenge_id")
            for item in values
            if item.get("effect_status") == effect
        )

    open_blocking = [
        item.get("challenge_id")
        for item in unresolved
        if item.get("blocking", True)
        and item.get("lifecycle_state") in {None, "OPEN"}
    ]
    summary = {
        "resolved_challenge_ids": ids(resolved),
        "unresolved_challenge_ids": ids(unresolved),
        "open_blocking_challenge_ids": _canonical_final_plan_unique(open_blocking),
        "applied_effect_challenge_ids": ids_with_effect(resolved, "APPLIED"),
        "suppressed_effect_challenge_ids": ids_with_effect(resolved, "SUPPRESSED"),
        "resolved_count": len(resolved),
        "unresolved_count": len(unresolved),
        "open_blocking_count": len(open_blocking),
        "provenance": DERIVED_PLAN_DECISION,
    }
    if reconciliation_hash:
        summary["reconciliation_hash"] = str(reconciliation_hash)
    return summary


def _canonical_final_plan_unique(values, *, text=False):
    """Return stable, duplicate-free values without lossy serialization."""
    result = []
    for value in list(values or []):
        if value in (None, "", [], {}):
            continue
        item = _compact(value, MAX_TEXT_CHARS) if text else str(value)
        if item and item not in result:
            result.append(item)
    return result


def _canonical_final_plan_surface_kind(surface_by_id, surface_id):
    surface = surface_by_id.get(str(surface_id), {}) if surface_by_id else {}
    return str(surface.get("kind", "")).upper()


def _canonical_final_plan_constraint_obligations(text, requirement_ids, ledger):
    """Bind shared preservation text to matching atomic obligations.

    The binding is deliberately conservative.  A generic preservation clause
    is allowed to support every preservation atom for its requirement, while
    a clause with a structured domain term is bound to the matching atom(s).
    No obligation is invented when the source text has no preservation
    meaning.
    """
    normalized = str(text or "").casefold()
    wanted = {str(item) for item in requirement_ids or []}
    result = []
    for record in _obligation_records(ledger):
        if wanted and str(record.get("requirement_id")) not in wanted:
            continue
        for atom in _atomic_obligations_for_requirement(record):
            if atom.get("obligation_type") != "PRESERVATION":
                continue
            atom_id = str(atom.get("obligation_id") or "")
            meaning = str(atom.get("meaning") or atom.get("text") or "").casefold()
            relations = " ".join(str(item) for item in atom.get("structured_relations", []) or []).casefold()
            relation_terms = set()
            if "owner" in meaning or "ownership" in relations:
                relation_terms.update({"owner", "ownership", "state"})
            if "escape" in meaning or "escape" in relations:
                relation_terms.add("escape")
            if "movement" in meaning or "movement" in relations:
                relation_terms.update({"movement", "input"})
            atom_terms = _domain_tokens(f"{meaning} {relations}")
            text_terms = _domain_tokens(normalized)
            matches = bool(relation_terms.intersection(text_terms)) or bool(atom_terms.intersection(text_terms))
            if not matches and re.search(r"\b(?:preserv|retain|keep|remain)\w*\b", normalized):
                # A source preservation clause may be intentionally generic.
                # Keeping it linked is safer than silently losing a required
                # preservation obligation during representation compaction.
                matches = True
            if matches and atom_id and atom_id not in result:
                result.append(atom_id)
    return result


def _canonical_final_plan_constraint_sources(plan, requirements, ledger,
                                             impact_map=None):
    """Collect shared constraint sources before canonical node grouping."""
    value = plan if isinstance(plan, dict) else {}
    req_ids = [item.get("requirement_id") for item in active_requirements(requirements)]
    sources = {}

    def add(kind, text, *, requirement_ids=None, node=None, surface_id=None):
        bounded = _compact(text, MAX_TEXT_CHARS)
        if not bounded:
            return
        key = (str(kind), bounded)
        record = sources.setdefault(key, {
            "kind": str(kind),
            "text": bounded,
            "requirement_ids": [],
            "source_node_ids": [],
            "source_surface_ids": [],
            "source_impact_ids": [],
            "obligation_ids": [],
        })
        for item in list(requirement_ids or []):
            if item and str(item) not in record["requirement_ids"]:
                record["requirement_ids"].append(str(item))
        if node:
            node_id = str(node.get("node_id") or "")
            if node_id and node_id not in record["source_node_ids"]:
                record["source_node_ids"].append(node_id)
            for item in list(node.get("surface_ids", []) or []) + list(
                node.get("target_surface_ids", []) or []
            ) + list(node.get("inspect_surface_ids", []) or []):
                if item and str(item) not in record["source_surface_ids"]:
                    record["source_surface_ids"].append(str(item))
            for item in node.get("impact_ids", []) or []:
                if item and str(item) not in record["source_impact_ids"]:
                    record["source_impact_ids"].append(str(item))
            for item in node.get("obligation_ids", []) or []:
                if item and str(item) not in record["obligation_ids"]:
                    record["obligation_ids"].append(str(item))
        if surface_id and str(surface_id) not in record["source_surface_ids"]:
            record["source_surface_ids"].append(str(surface_id))

    for node in value.get("approved_change_nodes", []) or []:
        if not isinstance(node, dict):
            continue
        node_requirements = node.get("requirement_ids") or req_ids
        for field in ("local_preservation_constraints", "preservation_constraints", "preserve"):
            for text in node.get(field, []) or []:
                add("preservation", text, requirement_ids=node_requirements, node=node)
        for text in node.get("prohibition_constraints", []) or []:
            add("prohibition", text, requirement_ids=node_requirements, node=node)
    for item in value.get("preservation_only_surfaces", []) or []:
        if not isinstance(item, dict):
            continue
        node_requirements = item.get("requirement_ids") or req_ids
        surface_id = item.get("surface_id") or item.get("canonical_surface_id")
        for field in ("preservation_constraints", "reason"):
            for text in ([item.get(field)] if item.get(field) else []):
                add("preservation", text, requirement_ids=node_requirements, surface_id=surface_id)
        for text in item.get("prohibition_constraints", []) or []:
            add("prohibition", text, requirement_ids=node_requirements, surface_id=surface_id)
    for text in value.get("prohibition_constraints", []) or []:
        add("prohibition", text, requirement_ids=req_ids)
    for impact in (impact_map or {}).get("impacts", []) if isinstance(impact_map, dict) else []:
        if not isinstance(impact, dict):
            continue
        for field in ("dnt", "prohibitions", "prohibition_constraints"):
            for text in impact.get(field, []) or []:
                add(
                    "prohibition", text,
                    requirement_ids=impact.get("requirement_ids") or req_ids,
                    surface_id=impact.get("surface_id"),
                )
    return sources


def _canonical_final_plan_protected_surfaces(plan, constraints, surface_by_id):
    """Resolve structured prohibition paths to canonical DNT surfaces."""
    value = plan if isinstance(plan, dict) else {}
    registry = surface_by_id if isinstance(surface_by_id, dict) else {}
    by_path = {
        _normal_path(item.get("path")).casefold(): str(surface_id)
        for surface_id, item in registry.items()
        if isinstance(item, dict) and item.get("path")
    }
    surface_ids = _canonical_final_plan_unique(
        value.get("do_not_touch_surface_ids", []) or []
    )
    paths = _canonical_final_plan_unique(value.get("do_not_touch", []) or [])

    def add_path(path):
        normalized = _normal_path(path)
        if not normalized:
            return
        surface_id = by_path.get(normalized.casefold())
        if surface_id and surface_id not in surface_ids:
            surface_ids.append(surface_id)
        canonical_path = (
            _normal_path(registry[surface_id].get("path"))
            if surface_id in registry else normalized
        )
        if canonical_path and canonical_path not in paths:
            paths.append(canonical_path)

    for path in list(paths):
        add_path(path)
    for record in list((constraints or {}).get("prohibitions", []) or []):
        text = record.get("text") if isinstance(record, dict) else record
        match = re.search(
            r"\b(?:do not|don't|must not|never)\s+"
            r"(?:modify|touch|edit|change)\s+([^\s,;]+)",
            str(text or ""),
            re.IGNORECASE,
        )
        if match:
            add_path(str(match.group(1)).rstrip("."))
    return (
        _canonical_final_plan_unique(surface_ids),
        _canonical_final_plan_unique(paths),
    )


def _canonical_final_plan_group_key(node, index, surface_by_id):
    value = node if isinstance(node, dict) else {}
    kind = str(value.get("impact_kind") or "").upper()
    disposition = str(value.get("disposition") or "").upper()
    if kind == "TEST_CHANGE" or disposition == "TEST_CHANGE":
        # Explicit test-change authority is kept as its own responsibility.
        return ("TEST_CHANGE", index)
    if bool(value.get("mutation_required")) and not bool(value.get("verification_only")):
        return ("EXECUTION_CHANGE", index)
    if kind == "INTERFACE_REUSE" or disposition == "INTERFACE_REUSE":
        return ("INTERFACE_REUSE",)
    if kind == "PRESERVATION_ONLY" or disposition == "PRESERVATION_ONLY":
        return ("PRESERVATION_ONLY", index)
    surface_ids = list(value.get("surface_ids", []) or []) + list(
        value.get("inspect_surface_ids", []) or []
    )
    if any(
        _canonical_final_plan_surface_kind(surface_by_id, item) == "TEST"
        for item in surface_ids
    ):
        return ("EVIDENCE_ONLY",)
    return ("DETERMINISTIC_CONTEXT",)


def _canonical_final_plan_short_done_when(responsibility):
    return {
        "EXECUTION_CHANGE": "Apply the approved implementation change through the verified current surface.",
        "TEST_CHANGE": "Run the approved test-change verification contract.",
        "INTERFACE_REUSE": "Verify reuse of the existing interface without changing ownership.",
        "PRESERVATION_ONLY": "Verify the approved preservation responsibility without mutation.",
        "EVIDENCE_ONLY": "Run the shared verification contracts for the referenced evidence.",
        "DETERMINISTIC_CONTEXT": "Verify the referenced evidence and shared preservation constraints.",
    }.get(str(responsibility), "Verify the approved responsibility.")


def _canonical_final_plan_semantic_projection(semantic):
    """Keep semantic results auditable without repeating atomic prose."""
    value = semantic if isinstance(semantic, dict) else {}
    result = {
        key: value.get(key)
        for key in (
            "requirements_covered", "requirements_uncovered", "behavior_obligations",
            "behavior_obligations_covered", "behavior_obligations_uncovered",
            "atomic_obligations_total", "atomic_behavior_change_obligations",
            "atomic_behavior_change_obligations_covered",
            "atomic_behavior_change_obligations_uncovered",
        ) if key in value
    }
    result["requirements"] = []
    for record in value.get("requirements", []) or []:
        if not isinstance(record, dict):
            continue
        result["requirements"].append({
            "requirement_id": record.get("requirement_id"),
            "obligation_types": list(record.get("obligation_types", []) or []),
            "obligations": [{
                "obligation_type": item.get("obligation_type"),
                "state": item.get("state"),
                "support": list(item.get("support", []) or []),
            } for item in record.get("obligations", []) or [] if isinstance(item, dict)],
            "atomic_obligations": [{
                key: item.get(key)
                for key in ("obligation_id", "obligation_type", "state", "support")
                if item.get(key) not in (None, "", [], {})
            } for item in record.get("atomic_obligations", []) or [] if isinstance(item, dict)],
            "state": record.get("state"),
            "provenance": record.get("provenance", DERIVED_PLAN_DECISION),
        })
    result["provenance"] = DERIVED_PLAN_DECISION
    return result


def canonicalize_final_plan(plan, impact_map=None, requirements=None, evidence=None,
                            surface_registry=None, source_impact_map=None):
    """Build the bounded V24 canonical approval-plan representation.

    This representation is enabled only for an explicit obligation-aware
    artifact.  Legacy Stage 3 plans are returned byte-for-byte in structure,
    so this compatibility repair cannot impose V24 continuation semantics on
    earlier fixtures.  The function groups only non-authoritative repeated
    context; mutation targets, test-change authority, DNT, requirements,
    evidence references, and deterministic provenance remain explicit.
    """
    source = copy.deepcopy(plan if isinstance(plan, dict) else {})
    if not _is_obligation_aware_artifact(source, source.get("requirement_obligation_ledger")):
        return source
    reqs = active_requirements(requirements or source.get("requirements", []))
    ledger = source.get("requirement_obligation_ledger")
    if not isinstance(ledger, dict):
        ledger = build_requirement_obligation_ledger(reqs)
    registry = surface_registry if isinstance(surface_registry, dict) else {}
    surface_by_id = canonical_surface_by_id(registry) if registry else {}
    raw_nodes = [item for item in source.get("approved_change_nodes", []) or [] if isinstance(item, dict)]
    raw_by_id = {str(item.get("node_id")): item for item in raw_nodes if item.get("node_id")}
    groups = []
    group_by_key = {}
    raw_group_keys = [
        _canonical_final_plan_group_key(node, index, surface_by_id)
        for index, node in enumerate(raw_nodes, 1)
    ]
    # An INTERFACE_REUSE responsibility is approval-relevant context, but it
    # is not an independent Worker/Builder action.  When the plan already
    # has a deterministic context group, fan the interface binding into that
    # group so the canonical plan has one context responsibility.  Keep an
    # interface-only group distinct: Stage 4 may need that orphan context
    # responsibility when there is no executable owner to attach it to.
    has_deterministic_context_group = any(
        key[0] == "DETERMINISTIC_CONTEXT" for key in raw_group_keys
    )
    for index, node in enumerate(raw_nodes, 1):
        key = raw_group_keys[index - 1]
        if has_deterministic_context_group and key[0] == "INTERFACE_REUSE":
            key = ("DETERMINISTIC_CONTEXT",)
        group = group_by_key.get(key)
        if group is None:
            group = {"key": key, "nodes": []}
            group_by_key[key] = group
            groups.append(group)
        group["nodes"].append(node)

    node_id_map = {}
    for position, group in enumerate(groups, 1):
        canonical_id = f"NODE-{position:03d}"
        group["canonical_id"] = canonical_id
        for node in group["nodes"]:
            if node.get("node_id"):
                node_id_map[str(node.get("node_id"))] = canonical_id

    def unique_field(nodes, field):
        return _canonical_final_plan_unique(
            value for node in nodes for value in (node.get(field, []) or [])
        )

    impact_by_id = {}
    if isinstance(impact_map, dict):
        impact_by_id = {
            str(item.get("impact_id")): item
            for item in impact_map.get("impacts", []) or []
            if isinstance(item, dict) and item.get("impact_id")
        }
    source_impact_by_id = {}
    if isinstance(source_impact_map, dict):
        source_impact_by_id = {
            str(item.get("impact_id")): item
            for item in source_impact_map.get("impacts", []) or []
            if isinstance(item, dict) and item.get("impact_id")
        }
    canonical_nodes = []
    group_original_constraint_keys = {}
    group_original_verification_keys = {}
    constraint_sources = _canonical_final_plan_constraint_sources(
        source, reqs, ledger, source_impact_map or impact_map,
    )
    verification_sources = {}

    def add_verification(text, node):
        bounded = _compact(text, MAX_TEXT_CHARS)
        if not bounded:
            return
        key = bounded
        record = verification_sources.setdefault(key, {
            "text": bounded, "source_node_ids": [], "requirement_ids": [],
            "evidence_ids": [], "surface_ids": [],
        })
        node_id = str(node.get("node_id") or "")
        if node_id and node_id not in record["source_node_ids"]:
            record["source_node_ids"].append(node_id)
        for field, target in (
            ("requirement_ids", "requirement_ids"),
            ("evidence_ids", "evidence_ids"),
            ("surface_ids", "surface_ids"),
        ):
            for item in node.get(field, []) or []:
                if item and str(item) not in record[target]:
                    record[target].append(str(item))

    for node in raw_nodes:
        contracts = list(node.get("local_test_contract", []) or []) + list(
            node.get("test_contract", []) or []
        )
        if not contracts and (
            str(node.get("impact_kind", "")).upper() == "TEST_CHANGE"
            or str(node.get("disposition", "")).upper() == "TEST_CHANGE"
        ):
            contracts = list(node.get("done_when", []) or [])
        for contract in contracts:
            add_verification(contract, node)

    for group in groups:
        nodes = group["nodes"]
        first = nodes[0]
        key_name = group["key"][0]
        if key_name == "EXECUTION_CHANGE":
            responsibility = "EXECUTION_CHANGE"
        elif key_name == "TEST_CHANGE":
            responsibility = "TEST_CHANGE"
        else:
            responsibility = key_name
        all_impact_ids = unique_field(nodes, "impact_ids")
        obligations = unique_field(nodes, "obligation_ids")
        for impact_id in all_impact_ids:
            impact_record = impact_by_id.get(str(impact_id)) or source_impact_by_id.get(str(impact_id), {})
            source_record = source_impact_by_id.get(str(impact_id), {})
            obligations.extend(
                str(item) for item in list(impact_record.get("obligation_ids", []) or [])
                + list(source_record.get("obligation_ids", []) or [])
                if item and str(item) not in obligations
            )
        obligations = _canonical_final_plan_unique(obligations)
        target_surface_ids = unique_field(nodes, "target_surface_ids")
        inspect_surface_ids = unique_field(nodes, "inspect_surface_ids")
        surface_ids = unique_field(nodes, "surface_ids")
        interface_surface_ids = unique_field(nodes, "interface_surface_ids")
        candidate_targets = unique_field(nodes, "candidate_targets") if responsibility in {
            "EXECUTION_CHANGE", "TEST_CHANGE"
        } else []
        inspect_targets = unique_field(nodes, "inspect_targets") if responsibility not in {
            "EXECUTION_CHANGE", "TEST_CHANGE"
        } else unique_field(nodes, "inspect_targets")
        impact_kinds = _canonical_final_plan_unique(node.get("impact_kind") for node in nodes)
        dispositions = _canonical_final_plan_unique(node.get("disposition") for node in nodes)
        necessities = _canonical_final_plan_unique(node.get("necessity_status") for node in nodes)
        if responsibility == "EXECUTION_CHANGE":
            impact_kind = impact_kinds[0] if len(impact_kinds) == 1 else "CROSS_CUTTING_VERIFICATION"
            disposition = "MUST_CHANGE" if "MUST_CHANGE" in dispositions else (dispositions[0] if dispositions else "MUST_CHANGE")
            necessity = "MUST_CHANGE" if "MUST_CHANGE" in necessities else (necessities[0] if necessities else "MUST_CHANGE")
        elif responsibility == "TEST_CHANGE":
            impact_kind = "TEST_CHANGE"
            disposition = "TEST_CHANGE"
            necessity = "TEST_CHANGE"
        elif responsibility == "INTERFACE_REUSE":
            impact_kind = "INTERFACE_REUSE"
            disposition = "INTERFACE_REUSE"
            necessity = "CANDIDATE"
        elif responsibility == "PRESERVATION_ONLY":
            impact_kind = "PRESERVATION_ONLY"
            disposition = "PRESERVATION_ONLY"
            necessity = "PRESERVATION_ONLY"
        else:
            impact_kind = "CROSS_CUTTING_VERIFICATION"
            disposition = "VERIFY_ONLY"
            necessity = "CANDIDATE"
        canonical_node = {
            "node_id": group["canonical_id"],
            # The model rationale is already bounded and hash-bound in the
            # upstream choice artifact.  It is intentionally not copied into
            # the approval authority for every grouped node; canonical goals
            # are deterministic responsibility labels instead.
            "goal": _canonical_final_plan_short_done_when(responsibility),
            "requirement_ids": unique_field(nodes, "requirement_ids"),
            "impact_ids": all_impact_ids,
            "obligation_ids": obligations,
            "evidence_ids": unique_field(nodes, "evidence_ids"),
            "surface_ids": surface_ids,
            "target_surface_ids": target_surface_ids,
            "inspect_surface_ids": inspect_surface_ids,
            "interface_surface_ids": interface_surface_ids,
            "current_owner": _compact(
                next((node.get("current_owner") for node in nodes if node.get("current_owner")), ""),
                180,
            ),
            "interfaces_to_reuse": unique_field(nodes, "interfaces_to_reuse"),
            "candidate_targets": candidate_targets,
            "inspect_targets": inspect_targets,
            "mutation_required": responsibility in {"EXECUTION_CHANGE", "TEST_CHANGE"}
            and any(bool(node.get("mutation_required")) for node in nodes),
            "verification_only": not (
                responsibility in {"EXECUTION_CHANGE", "TEST_CHANGE"}
                and any(bool(node.get("mutation_required")) for node in nodes)
            ),
            "done_when": [_canonical_final_plan_short_done_when(responsibility)],
            "dependencies": [],
            "impact_kind": impact_kind,
            "necessity_status": necessity,
            "disposition": disposition,
            "responsibility_class": responsibility,
            "source_node_ids": [str(node.get("node_id")) for node in nodes if node.get("node_id")],
            "provenance": DERIVED_PLAN_DECISION,
        }
        for field in (
            "new_surface_proposal_ids", "target_new_surface_proposal_ids",
            "inspect_new_surface_proposal_ids", "parent_scopes",
        ):
            values = unique_field(nodes, field)
            if values:
                canonical_node[field] = values
        proposals = [
            copy.deepcopy(item) for node in nodes
            for item in node.get("new_surface_proposals", []) or []
            if isinstance(item, dict)
        ]
        if proposals:
            canonical_node["new_surface_proposals"] = proposals
        node_constraint_keys = []
        node_verification_keys = []
        for node in nodes:
            node_id = str(node.get("node_id") or "")
            for (kind, text), record in constraint_sources.items():
                if node_id in record["source_node_ids"] and (kind, text) not in node_constraint_keys:
                    node_constraint_keys.append((kind, text))
            for text, record in verification_sources.items():
                if node_id in record["source_node_ids"] and text not in node_verification_keys:
                    node_verification_keys.append(text)
        group_original_constraint_keys[group["canonical_id"]] = node_constraint_keys
        group_original_verification_keys[group["canonical_id"]] = node_verification_keys
        canonical_nodes.append(canonical_node)

    # Create shared constraint records after canonical node IDs are known.
    constraint_records = {"preservation": [], "prohibitions": []}
    constraint_id_by_key = {}
    for index, ((kind, text), record) in enumerate(constraint_sources.items(), 1):
        constraint_id = f"CONSTRAINT-{index:03d}"
        constraint_id_by_key[(kind, text)] = constraint_id
        obligation_ids = _canonical_final_plan_unique(record.get("obligation_ids"))
        if kind == "preservation":
            for item in _canonical_final_plan_constraint_obligations(
                text, record.get("requirement_ids"), ledger,
            ):
                if item not in obligation_ids:
                    obligation_ids.append(item)
        constraint = {
            "constraint_id": constraint_id,
            "text": text,
            "requirement_ids": _canonical_final_plan_unique(record.get("requirement_ids")),
            "obligation_ids": obligation_ids,
            "provenance": DERIVED_PLAN_DECISION,
        }
        constraint_records["preservation" if kind == "preservation" else "prohibitions"].append(constraint)
    for node in canonical_nodes:
        source_keys = group_original_constraint_keys.get(node["node_id"], [])
        node["constraint_ids"] = _canonical_final_plan_unique(
            constraint_id_by_key.get(key) for key in source_keys
        )
        for impact_id in node.get("impact_ids", []) or []:
            for impact_source in (
                impact_by_id.get(str(impact_id), {}),
                source_impact_by_id.get(str(impact_id), {}),
            ):
                for field in ("dnt", "prohibitions", "prohibition_constraints"):
                    for text in impact_source.get(field, []) or []:
                        constraint_id = constraint_id_by_key.get(
                            ("prohibition", _compact(text, MAX_TEXT_CHARS))
                        )
                        if constraint_id and constraint_id not in node["constraint_ids"]:
                            node["constraint_ids"].append(constraint_id)
        node["verification_ids"] = []
        for source_key in group_original_verification_keys.get(node["node_id"], []):
            if source_key in verification_sources:
                # Assigned below once verification IDs have been made stable.
                node["verification_ids"].append(source_key)
        node["verification_ids"] = _canonical_final_plan_unique(node["verification_ids"])

    verification_records = []
    verification_id_by_text = {}
    for index, (text, record) in enumerate(verification_sources.items(), 1):
        verification_id = f"VERIFICATION-{index:03d}"
        verification_id_by_text[text] = verification_id
        surface_ids = _canonical_final_plan_unique(record.get("surface_ids"))
        verification_records.append({
            "verification_id": verification_id,
            "contract": [text],
            "requirement_ids": _canonical_final_plan_unique(record.get("requirement_ids")),
            "evidence_ids": _canonical_final_plan_unique(record.get("evidence_ids")),
            "surface_ids": surface_ids,
            "node_ids": _canonical_final_plan_unique(
                node_id_map.get(item) for item in record.get("source_node_ids", [])
            ),
            "provenance": DERIVED_PLAN_DECISION,
        })
    for node in canonical_nodes:
        node["verification_ids"] = [
            verification_id_by_text[item]
            for item in node.get("verification_ids", [])
            if item in verification_id_by_text
        ]

    # Remap dependency and test responsibility references through the grouped
    # nodes.  Explicit test-change nodes are never merged into evidence-only
    # context, so their execution semantics remain distinguishable.
    for node in canonical_nodes:
        original_ids = set(node.get("source_node_ids", []))
        dependencies = []
        for source_id in original_ids:
            original = raw_by_id.get(source_id, {})
            for dependency in original.get("dependencies", []) or []:
                mapped = node_id_map.get(str(dependency))
                if mapped and mapped != node["node_id"] and mapped not in dependencies:
                    dependencies.append(mapped)
        node["dependencies"] = dependencies

    canonical_tests = []
    for item in source.get("tests_to_update_or_add", []) or []:
        if not isinstance(item, dict):
            continue
        test = copy.deepcopy(item)
        if test.get("node_id") in node_id_map:
            test["node_id"] = node_id_map[str(test.get("node_id"))]
        canonical_tests.append(test)

    canonical_preservation = []
    for item in source.get("preservation_only_surfaces", []) or []:
        if not isinstance(item, dict):
            continue
        compact = copy.deepcopy(item)
        compact.pop("preservation_constraints", None)
        compact.pop("reason", None)
        compact.pop("prohibition_constraints", None)
        compact["constraint_ids"] = []
        item_req_ids = item.get("requirement_ids") or [req.get("requirement_id") for req in reqs]
        surface_id = item.get("surface_id") or item.get("canonical_surface_id")
        for field, kind in (
            ("preservation_constraints", "preservation"),
            ("prohibition_constraints", "prohibition"),
        ):
            values = list(item.get(field, []) or [])
            if field == "preservation_constraints" and item.get("reason"):
                values.append(item.get("reason"))
            for text in values:
                key = (kind, _compact(text, MAX_TEXT_CHARS))
                if key in constraint_id_by_key and constraint_id_by_key[key] not in compact["constraint_ids"]:
                    compact["constraint_ids"].append(constraint_id_by_key[key])
        canonical_preservation.append(compact)

    # Every impact remains reachable from a canonical responsibility.  The
    # references carry deterministic decision authority and provenance while
    # avoiding a second copy of model prose for each repeated context node.
    impact_references = []
    source_impacts = list(impact_map.get("impacts", []) or []) if isinstance(impact_map, dict) else []
    if not source_impacts:
        source_impacts = [
            {"impact_id": impact_id, "surface_id": surface_id}
            for node in raw_nodes
            for impact_id in node.get("impact_ids", []) or []
            for surface_id in node.get("surface_ids", [])[:1]
        ]
    for item in source_impacts:
        if not isinstance(item, dict) or not item.get("impact_id"):
            continue
        impact_id = str(item.get("impact_id"))
        source_node = next(
            (node for node in raw_nodes if impact_id in [str(value) for value in node.get("impact_ids", []) or []]),
            {},
        )
        source_item = source_impact_by_id.get(impact_id, {})
        ref = {
            "impact_id": impact_id,
            "node_id": node_id_map.get(str(source_node.get("node_id"))),
            "surface_id": item.get("surface_id") or source_item.get("surface_id") or (source_node.get("surface_ids") or [None])[0],
            "obligation_ids": _canonical_final_plan_unique(item.get("obligation_ids") or source_item.get("obligation_ids") or source_node.get("obligation_ids")),
            "impact_kind": item.get("impact_kind") or source_item.get("impact_kind") or source_node.get("impact_kind"),
            "disposition": item.get("disposition") or source_item.get("disposition") or source_node.get("disposition"),
            "chosen_decision": item.get("chosen_decision") or source_item.get("chosen_decision"),
            "decision_capabilities": _canonical_final_plan_unique(item.get("decision_capabilities") or source_item.get("decision_capabilities")),
            "decision_slot_id": item.get("decision_slot_id") or source_item.get("decision_slot_id"),
            "provenance": DERIVED_PLAN_DECISION,
        }
        impact_references.append({
            key: value for key, value in ref.items()
            if value not in (None, "", [], {})
        })

    # Normalize challenge state before binding its identity.  Model claim and
    # proposal text is deliberately excluded from the approval representation
    # even when a direct caller supplies the richer validated record.
    resolved = [
        _plan_challenge_record(item)
        for item in list(source.get("resolved_challenges", []) or [])
        if isinstance(item, dict)
    ][:MAX_CHALLENGES]
    unresolved = [
        _plan_challenge_record(item)
        for item in list(source.get("unresolved_challenges", []) or [])
        if isinstance(item, dict)
    ][:MAX_CHALLENGES]
    challenge_reconciliation_hash = _impact_decision_hash({
        "resolved_challenges": resolved,
        "unresolved_challenges": unresolved,
    })
    upstream = {
        "planning_mode": source.get("planning_mode"),
        "requirements_hash": _impact_decision_hash(reqs),
        "challenge_reconciliation_hash": challenge_reconciliation_hash,
        "provenance": DERIVED_PLAN_DECISION,
    }
    binding = source.get("verified_planning_context")
    if isinstance(binding, dict):
        for key in (
            "planning_context_hash", "source_task_brain_hash", "source_project_brain_hash",
            "source_repository_evidence_hash", "source_reentry_hash",
        ):
            if binding.get(key):
                upstream[key] = binding.get(key)
    if isinstance(impact_map, dict):
        for source_key, target_key in (
            ("impact_decision_frame_hash", "impact_decision_frame_hash"),
            ("impact_decision_choice_hash", "impact_decision_choice_hash"),
            ("source_planning_context_hash", "source_planning_context_hash"),
            ("source_mandatory_core_hash", "source_mandatory_core_hash"),
        ):
            source_value = impact_map.get(source_key)
            if not source_value and isinstance(source_impact_map, dict):
                source_value = source_impact_map.get(source_key)
            if source_value:
                upstream[target_key] = source_value
        upstream["impact_map_hash"] = challenger_review_source_map_hash(impact_map)

    result = copy.deepcopy(source)
    result["version"] = CANONICAL_FINAL_PLAN_VERSION
    result["representation"] = CANONICAL_FINAL_PLAN_REPRESENTATION
    result["approved_change_nodes"] = canonical_nodes
    result["preservation_only_surfaces"] = canonical_preservation
    result["tests_to_update_or_add"] = canonical_tests
    result["prohibition_constraints"] = []
    result["canonical_constraints"] = {
        "version": 1,
        "preservation": constraint_records["preservation"],
        "prohibitions": constraint_records["prohibitions"],
        "provenance": DERIVED_PLAN_DECISION,
    }
    result["canonical_verification_contracts"] = verification_records
    result["impact_references"] = impact_references
    result["upstream_bindings"] = upstream
    if resolved or unresolved:
        # Keep only a compact, hash-bound outcome index in the approval plan.
        # The complete validated review and reconciliation remain reachable
        # through the immutable upstream artifact identified by this hash.
        result["challenger_reconciliation"] = _canonical_final_plan_challenge_summary(
            resolved, unresolved, challenge_reconciliation_hash,
        )
    else:
        result.pop("challenger_reconciliation", None)
    result.pop("resolved_challenges", None)
    result.pop("unresolved_challenges", None)
    result["planning_provenance"] = [
        {
            key: copy.deepcopy(item.get(key))
            for key in ("source", "ids", "paths")
            if item.get(key) not in (None, "", [], {})
        }
        for item in result.get("planning_provenance", []) or []
        if isinstance(item, dict) and (
            item.get("ids") not in (None, "", [], {})
            or item.get("paths") not in (None, "", [], {})
        )
    ]
    dnt_surface_ids, dnt_paths = _canonical_final_plan_protected_surfaces(
        result,
        result["canonical_constraints"],
        surface_by_id,
    )
    if dnt_surface_ids:
        result["do_not_touch_surface_ids"] = dnt_surface_ids
    else:
        result.pop("do_not_touch_surface_ids", None)
    if dnt_paths:
        result["do_not_touch"] = dnt_paths
    else:
        result.pop("do_not_touch", None)
    result["evidence_refs"] = _canonical_final_plan_unique(
        value for node in canonical_nodes for value in node.get("evidence_ids", [])
    ) + _canonical_final_plan_unique(
        value for item in canonical_preservation for value in item.get("evidence_ids", [])
    )
    result["evidence_refs"] = _canonical_final_plan_unique(result["evidence_refs"])

    # Rebuild requirement coverage against canonical node IDs and expose the
    # deterministic semantic audit in compact form.  The evaluator consumes
    # the shared catalog, so preservation atoms are not lost by node grouping.
    semantic = evaluate_requirement_obligations(
        {
            "approved_change_nodes": canonical_nodes,
            "preservation_only_surfaces": canonical_preservation,
            "canonical_constraints": result["canonical_constraints"],
            "integration_verification": result.get("integration_verification"),
            "prohibition_constraints": result.get("prohibition_constraints"),
        }, reqs, evidence or [], registry, ledger,
    )
    coverage = []
    for requirement in reqs:
        requirement_id = requirement.get("requirement_id")
        record = next(
            (item for item in semantic.get("requirements", [])
             if item.get("requirement_id") == requirement_id),
            {},
        )
        linked_nodes = [
            node for node in canonical_nodes
            if requirement_id in node.get("requirement_ids", [])
        ]
        types = set(record.get("obligation_types", []) or [])
        if record.get("state") != "COVERED":
            status = "UNASSIGNED"
        elif "BEHAVIOR_CHANGE" in types:
            status = "COVERED_BY_CHANGE"
        elif "TEST" in types:
            status = "COVERED_BY_TEST"
        elif "PRESERVATION" in types:
            status = "COVERED_BY_PRESERVATION"
        else:
            status = "CROSS_CUTTING"
        coverage.append({
            "requirement_id": requirement_id,
            "status": status,
            "node_ids": [node.get("node_id") for node in linked_nodes],
            "impact_ids": _canonical_final_plan_unique(
                impact_id for node in linked_nodes for impact_id in node.get("impact_ids", [])
            ),
            "preservation_surface_ids": _canonical_final_plan_unique(
                item.get("surface_id") for item in canonical_preservation
                if requirement_id in item.get("requirement_ids", [])
            ),
            "obligation_ids": _canonical_final_plan_unique(
                obligation_id for node in linked_nodes for obligation_id in node.get("obligation_ids", [])
            ),
            "obligation_types": list(record.get("obligation_types", []) or []),
            "semantic_state": record.get("state", "UNCOVERED"),
            "provenance": DERIVED_PLAN_DECISION,
        })
    result["coverage"] = coverage
    result["semantic_obligation_coverage"] = _canonical_final_plan_semantic_projection(semantic)
    result["provenance"] = dict(result.get("provenance", {}) or {})
    result["provenance"]["canonical_representation"] = DERIVED_PLAN_DECISION
    # Empty legacy projection sections carry no authority in a canonical
    # plan.  Omit only those empty containers; populated responsibilities and
    # all shared authority catalogs remain explicit.
    for field in (
        "preservation_only_surfaces", "tests_to_update_or_add",
        "new_surface_proposals", "unresolved_challenges",
        "behavior_anchor_closure_actions", "prohibition_constraints",
        "mutation_new_surface_proposal_ids",
    ):
        if not result.get(field):
            result.pop(field, None)
    if _json_size(result) > MAX_PLAN_CHARS:
        # The semantic audit is derived and recomputed by the Plan Gate.  It
        # may be omitted only when the complete canonical representation is
        # still over the hard bound after structural compaction.
        result.pop("semantic_obligation_coverage", None)
    if _json_size(result) > MAX_PLAN_CHARS:
        result = _fit_plan_to_serialized_bound(result)
    return finalize_plan_identity(result)


canonical_final_plan = canonicalize_final_plan


def _fit_plan_to_serialized_bound(plan):
    """Trim only redundant compatibility projections when the plan is tight."""
    value = plan if isinstance(plan, dict) else {}
    if value.get("representation") == CANONICAL_FINAL_PLAN_REPRESENTATION:
        if _json_size(value) > MAX_PLAN_CHARS:
            value.pop("semantic_obligation_coverage", None)
        return value
    # These fields are retained in ordinary plans for compatibility, but are
    # exact projections of canonical fields already present in the node.  A
    # newly confirmed requirement can otherwise push an otherwise valid plan
    # a few characters beyond the fixed Stage 3 bound.
    optional_node_fields = (
        "objective", "target_paths", "test_contract", "new_surface_proposals",
        "parent_scopes",
    )
    for field in optional_node_fields:
        if _json_size(value) <= MAX_PLAN_CHARS - 128:
            break
        for node in value.get("approved_change_nodes", []) or []:
            node.pop(field, None)
    # Semantic coverage is recomputed by the Plan Gate; retain it whenever
    # possible, but use it as the final compactability valve for unusually
    # verbose confirmed requirement text.
    if _json_size(value) > MAX_PLAN_CHARS - 128:
        value.pop("semantic_obligation_coverage", None)
    return value


def build_minimal_change_plan(impact_map, requirements, evidence, resolved_challenges=None,
                              unresolved_challenges=None, project_mode=EXISTING_PROJECT,
                              surface_registry=None, obligation_ledger=None,
                              task_goal=None, obligation_aware=None):
    reqs = active_requirements(requirements)
    supplied_ledger = obligation_ledger or (
        (impact_map or {}).get("requirement_obligation_ledger")
    )
    if obligation_aware is None:
        obligation_aware = _is_obligation_aware_artifact(impact_map, supplied_ledger)
    obligation_ledger = supplied_ledger or build_requirement_obligation_ledger(reqs)
    req_by_id = {item["requirement_id"]: item for item in reqs}
    evidence_by_id = {
        item["evidence_id"]: item for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    }
    impacts = list((impact_map or {}).get("impacts", []) or [])
    surface_by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    preservation, nodes, tests = [], [], []
    interface_reuse = []
    interface_surface_ids = []
    strict_surface_binding = bool(surface_registry)
    proposal_by_id = {
        str(item.get("proposal_id")): item
        for item in (impact_map or {}).get("new_surface_proposals", [])
        if isinstance(item, dict) and item.get("proposal_id")
    }
    for impact in impacts:
        req_ids = [item for item in impact.get("requirement_ids", []) if item in req_by_id]
        evidence_ids = [item for item in impact.get("repository_evidence_ids", []) if item in evidence_by_id]
        surface = surface_by_id.get(str(impact.get("surface_id"))) if strict_surface_binding else None
        proposal_ids = [
            item for item in _bounded_ids(impact.get("new_surface_proposal_ids"), 4)
            if item in proposal_by_id
        ]
        new_surface_binding = bool(proposal_ids) and not surface
        if strict_surface_binding and not surface and not new_surface_binding:
            continue
        disposition = str(impact.get("disposition") or "").upper()
        if impact.get("necessity_status") == "INSUFFICIENT_EVIDENCE" or disposition == "INSUFFICIENT_EVIDENCE":
            continue
        if impact.get("impact_kind") == "PRESERVATION_ONLY" or impact.get("necessity_status") == "PRESERVATION_ONLY" or disposition == "PRESERVATION_ONLY":
            preservation.append(_surface_record(impact, surface_registry))
            continue
        if not req_ids or (
            project_mode == EXISTING_PROJECT and not evidence_ids and not new_surface_binding
        ):
            continue
        kind = impact.get("impact_kind")
        mutation_required = impact.get("necessity_status") == "MUST_CHANGE" or disposition in {"MUST_CHANGE", "TEST_CHANGE"}
        if impact.get("necessity_status") == "CANDIDATE":
            mutation_required = (
                kind in {"BEHAVIOR_CHANGE", "INTEGRATION_CHANGE", "TEST_CHANGE"}
                and _requirement_change_required(req_ids, req_by_id)
            )
        if kind in {"INTERFACE_REUSE", "CROSS_CUTTING_VERIFICATION"} or disposition in {"INTERFACE_REUSE", "VERIFY_ONLY"}:
            mutation_required = False
        interfaces = _bounded_strings(impact.get("existing_interfaces_to_reuse"), 6, 180)
        linked_interface_ids = _bounded_ids(
            impact.get("interfaces_to_reuse") or impact.get("interface_surface_ids"), 6,
        )
        if strict_surface_binding:
            linked_interface_ids = [
                item for item in linked_interface_ids
                if item in surface_by_id and surface_by_id[item].get("kind") == "INTERFACE"
            ]
            interfaces = _bounded_strings([
                surface_by_id[item].get("symbol") for item in linked_interface_ids
            ], 6, 180)
        interface_reuse.extend(interfaces)
        interface_surface_ids.extend(linked_interface_ids)
        path = _normal_path((surface or impact).get("path", ""))
        surface_id = (surface or impact).get("surface_id") or impact.get("canonical_surface_id")
        canonical_evidence_ids = list((surface or {}).get("evidence_ids", []) or evidence_ids)
        selected_proposals = [proposal_by_id[item] for item in proposal_ids]
        node = {
            "node_id": f"NODE-{len(nodes) + 1:03d}",
            "goal": _compact(impact.get("candidate_change") or impact.get("reason"), 700),
            "requirement_ids": req_ids,
            "impact_ids": [impact.get("impact_id")],
            "evidence_ids": canonical_evidence_ids,
            "surface_ids": [surface_id] if surface_id else [],
            "target_surface_ids": [surface_id] if surface_id and mutation_required else [],
            "inspect_surface_ids": [surface_id] if surface_id and not mutation_required else [],
            "new_surface_proposal_ids": proposal_ids,
            "target_new_surface_proposal_ids": proposal_ids if mutation_required else [],
            "inspect_new_surface_proposal_ids": proposal_ids if not mutation_required else [],
            "new_surface_proposals": copy.deepcopy(selected_proposals),
            "parent_scopes": _bounded_strings(
                [item.get("parent_scope") for item in selected_proposals], 4, 240,
            ),
            "current_owner": _compact(
                (surface or {}).get("symbol") or impact.get("existing_owner"), 180,
            ),
            "interfaces_to_reuse": interfaces,
            "interface_surface_ids": linked_interface_ids,
            "candidate_targets": [path] if path and mutation_required else [],
            "inspect_targets": [path] if path and not mutation_required else [],
            "mutation_required": bool(mutation_required),
            "verification_only": not mutation_required,
            "local_preservation_constraints": _bounded_strings(
                impact.get("local_preservation_constraints") or impact.get("preserve"), 8, 300,
            ),
            "preservation_constraints": _bounded_strings(
                impact.get("local_preservation_constraints") or impact.get("preserve"), 8, 300,
            ),
            "prohibition_constraints": _bounded_strings(
                impact.get("prohibition_constraints"), 6, 320,
            ),
            "local_test_contract": _bounded_strings(impact.get("local_verification"), 6, 300),
            "done_when": _bounded_strings(
                impact.get("local_verification")
                or [req_by_id[item]["text"] for item in req_ids], 6, 300,
            ),
            "dependencies": [],
            "do_not_touch": [],
            "impact_kind": kind,
            "necessity_status": impact.get("necessity_status"),
            "disposition": disposition,
            "provenance": DERIVED_PLAN_DECISION,
        }
        if isinstance(impact.get("closure_metadata"), dict):
            node["closure_metadata"] = copy.deepcopy(impact.get("closure_metadata"))
        node["objective"] = node["goal"]
        node["target_paths"] = list(node["candidate_targets"])
        node["test_contract"] = list(node["local_test_contract"])
        nodes.append(node)
        if kind == "TEST_CHANGE":
            tests.append({
                "node_id": node["node_id"], "surface_id": surface_id, "path": path,
                "test_surface_ids": [surface_id] if surface_id else [],
                "new_surface_proposal_ids": proposal_ids,
                "requirement_ids": req_ids, "evidence_ids": canonical_evidence_ids,
                "contract": list(node["local_test_contract"] or node["done_when"]),
                "provenance": DERIVED_PLAN_DECISION,
            })
        if len(nodes) >= MAX_PLAN_NODES:
            break

    if strict_surface_binding:
        derived_do_not_touch = derive_do_not_touch_surface_ids(impact_map, surface_registry)
        do_not_touch_surface_ids = list(derived_do_not_touch["surface_ids"])
        do_not_touch = list(derived_do_not_touch["paths"])
    else:
        do_not_touch_surface_ids = []
        do_not_touch = _bounded_strings(
            [item.get("path") for item in preservation if item.get("path")], MAX_PLAN_NODES, 240,
        )
    test_nodes = [item["node_id"] for item in nodes if item.get("impact_kind") == "TEST_CHANGE"]
    behavior_nodes = [item["node_id"] for item in nodes if item.get("impact_kind") != "TEST_CHANGE"]
    all_test_contracts = _bounded_strings(
        [value for item in tests for value in item.get("contract", [])], 6, 300,
    )
    for node in nodes:
        node["do_not_touch"] = [
            path for path in do_not_touch if path not in set(node.get("candidate_targets", []))
        ]
        if node.get("impact_kind") == "TEST_CHANGE":
            node["dependencies"] = behavior_nodes[:4]
        elif all_test_contracts:
            node["local_test_contract"] = _bounded_strings(
                list(node.get("local_test_contract", [])) + all_test_contracts, 6, 300,
            )

    integration = _bounded_strings((impact_map or {}).get("integration_verification"), 10, 320)
    for item in preservation:
        if item.get("reason"):
            integration = _bounded_strings(
                integration + [f"Preserve without mutation: {item['reason']}"], 10, 320,
            )
    if tests:
        integration = _bounded_strings(integration + ["Run the approved relevant test contracts."], 10, 320)
    for obligation in _obligation_records(obligation_ledger):
        integration = _bounded_strings(
            integration + [_integration_check_for_obligation(obligation)], 12, 360,
        )
    if not integration:
        integration = ["Verify every approved responsibility and preservation constraint after fan-in."]

    prohibition_constraints = _bounded_strings([
        constraint
        for obligation in _obligation_records(obligation_ledger)
        for constraint in _prohibition_constraints(obligation.get("text"))
    ], 8, 320)
    semantic = evaluate_requirement_obligations({
        "approved_change_nodes": nodes,
        "preservation_only_surfaces": preservation,
        "integration_verification": integration,
        "prohibition_constraints": prohibition_constraints,
    }, reqs, evidence, surface_registry, obligation_ledger)
    semantic_by_id = {
        item["requirement_id"]: item for item in semantic.get("requirements", [])
    }
    coverage = []
    for requirement in reqs:
        requirement_id = requirement["requirement_id"]
        linked_nodes = [item for item in nodes if requirement_id in item.get("requirement_ids", [])]
        linked_preservation = [
            item for item in preservation if requirement_id in item.get("requirement_ids", [])
        ]
        semantic_record = semantic_by_id.get(requirement_id, {})
        types = set(semantic_record.get("obligation_types", []))
        if semantic_record.get("state") != "COVERED":
            status = "UNASSIGNED"
        elif "BEHAVIOR_CHANGE" in types:
            status = "COVERED_BY_CHANGE"
        elif "TEST" in types:
            status = "COVERED_BY_TEST"
        elif "PRESERVATION" in types:
            status = "COVERED_BY_PRESERVATION"
        else:
            status = "CROSS_CUTTING"
        coverage.append({
            "requirement_id": requirement_id,
            "status": status,
            "node_ids": [item["node_id"] for item in linked_nodes],
            "impact_ids": _bounded_ids([
                value for item in linked_nodes for value in item.get("impact_ids", [])
            ], 6),
            "preservation_surface_ids": _bounded_ids([
                item.get("surface_id") for item in linked_preservation
            ], 6),
            "obligation_types": list(semantic_record.get("obligation_types", [])),
            "semantic_state": semantic_record.get("state", "UNCOVERED"),
            "provenance": DERIVED_PLAN_DECISION,
        })

    plan = {
        "version": 1,
        "task_goal": (
            str(task_goal) if task_goal is not None
            else _compact((impact_map or {}).get("task_goal"), 1000)
            or (f"Fulfill active requirement: {reqs[0]['text']}" if reqs else "")
        ),
        "project_mode": project_mode,
        "requirements": reqs,
        "approved_change_nodes": nodes,
        "preservation_only_surfaces": preservation[:MAX_PLAN_NODES],
        "interfaces_to_reuse": _bounded_strings(interface_reuse, 10, 180),
        "interface_surface_ids": _bounded_ids(interface_surface_ids, 10),
        "tests_to_update_or_add": tests[:MAX_PLAN_NODES],
        "integration_verification": integration,
        "prohibition_constraints": prohibition_constraints,
        "do_not_touch": do_not_touch,
        "do_not_touch_surface_ids": do_not_touch_surface_ids,
        "mutation_surface_ids": sorted({
            str(value) for node in nodes for value in node.get("target_surface_ids", []) if value
        }),
        "mutation_new_surface_proposal_ids": sorted({
            str(value) for node in nodes
            for value in node.get("target_new_surface_proposal_ids", []) if value
        }),
        "canonical_surface_registry_version": (
            surface_registry.get("version") if surface_registry else None
        ),
        "new_surface_proposals": copy.deepcopy((impact_map or {}).get("new_surface_proposals", [])),
        "resolved_challenges": [
            _plan_challenge_record(item) for item in list(resolved_challenges or [])[:MAX_CHALLENGES]
        ],
        "unresolved_challenges": [
            _plan_challenge_record(item) for item in list(unresolved_challenges or [])[:MAX_CHALLENGES]
        ],
        "coverage": coverage,
        "requirement_obligation_ledger": (
            compact_requirement_obligation_ledger(obligation_ledger)
            if obligation_aware else
            _legacy_compact_requirement_obligation_ledger(obligation_ledger)
        ),
        "semantic_obligation_coverage": copy.deepcopy(
            semantic if obligation_aware else _legacy_semantic_obligation_coverage(semantic)
        ),
        "behavior_anchor_closure_actions": copy.deepcopy(
            (impact_map or {}).get("behavior_anchor_closure_actions", [])
        ),
        "evidence_refs": _bounded_ids([
            item for node in nodes for item in node.get("evidence_ids", [])
        ] + [item for surface in preservation for item in surface.get("evidence_ids", [])], 24),
        "provenance": {
            "task_goal": USER_STATED,
            "requirements": [USER_STATED, USER_CONFIRMED],
            "repository_facts": REPOSITORY_EVIDENCE,
            "plan_decisions": DERIVED_PLAN_DECISION,
        },
        "bounds": {
            "max_plan_nodes": MAX_PLAN_NODES,
            "max_impact_entries": MAX_IMPACT_ENTRIES,
            "max_challenges": MAX_CHALLENGES,
            "max_serialized_chars": MAX_PLAN_CHARS,
            "challenge_rounds": 1,
            "revision_rounds": min(1, int(bool(resolved_challenges or unresolved_challenges))),
        },
    }
    return finalize_plan_identity(_fit_plan_to_serialized_bound(plan))


def validate_change_plan(plan, requirements, evidence, project_mode=EXISTING_PROJECT,
                         surface_registry=None, obligation_ledger=None,
                         authoritative_task_goal=None, obligation_aware=None):
    value = plan if isinstance(plan, dict) else {}
    errors = []
    expected_obligation_ledger = obligation_ledger or build_requirement_obligation_ledger(requirements)
    if obligation_aware is None:
        obligation_aware = _is_obligation_aware_artifact(value, obligation_ledger)
    req_ids = {item["requirement_id"] for item in active_requirements(requirements)}
    evidence_ids = {item["evidence_id"] for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)}
    evidence_by_id = {
        item["evidence_id"]: item for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    }
    surface_by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    strict_surface_binding = bool(surface_registry)
    proposal_result = validate_new_surface_proposals(
        value.get("new_surface_proposals", []), requirements, surface_registry or {},
    ) if strict_surface_binding else {"validated": [], "rejected": []}
    proposal_by_id = {
        str(item.get("proposal_id")): item for item in proposal_result.get("validated", [])
    }
    if proposal_result.get("rejected"):
        errors.append("plan contains an invalid new-surface proposal")
    nodes = list(value.get("approved_change_nodes", []) or [])
    if len(nodes) > MAX_PLAN_NODES:
        errors.append("plan node bound exceeded")
    if value.get("plan_hash") != plan_content_hash(value):
        errors.append("plan hash does not match plan content")
    if value.get("plan_id") != f"PLAN-{str(value.get('plan_hash', ''))[:12].upper()}":
        errors.append("plan ID does not match plan hash")
    if not str(value.get("task_goal", "")).strip():
        errors.append("authoritative task goal is required")
    if authoritative_task_goal is not None and value.get("task_goal") != authoritative_task_goal:
        errors.append("task goal does not match the authoritative root goal")
    expected_compact_ledger = (
        compact_requirement_obligation_ledger(expected_obligation_ledger)
        if obligation_aware else
        _legacy_compact_requirement_obligation_ledger(expected_obligation_ledger)
    )
    if value.get("requirement_obligation_ledger") != expected_compact_ledger:
        errors.append("requirement obligation ledger is missing or not authoritative")
    do_not_touch = set(str(item) for item in value.get("do_not_touch", []))
    do_not_touch_surface_ids = {
        str(item) for item in value.get("do_not_touch_surface_ids", [])
    }
    mutation_surface_ids = set()
    mutation_paths = set()
    canonical_representation = value.get("representation") == CANONICAL_FINAL_PLAN_REPRESENTATION
    canonical_constraints = value.get("canonical_constraints")
    canonical_constraint_ids = set()
    canonical_verification_ids = set()
    canonical_obligation_ids = {
        str(item.get("obligation_id"))
        for item in _atomic_obligation_records(expected_obligation_ledger)
        if item.get("obligation_id")
    }
    known_node_ids = {
        str(item.get("node_id")) for item in nodes
        if isinstance(item, dict) and item.get("node_id")
    }
    if canonical_representation:
        if not isinstance(canonical_constraints, dict):
            errors.append("canonical final plan constraints are required")
        else:
            for field in ("preservation", "prohibitions"):
                records = canonical_constraints.get(field)
                if not isinstance(records, list):
                    errors.append(f"canonical final plan {field} constraints must be a list")
                    continue
                seen_constraint_ids = set()
                for record in records:
                    if not isinstance(record, dict) or not record.get("constraint_id") or not record.get("text"):
                        errors.append(f"canonical final plan {field} constraint is incomplete")
                        continue
                    constraint_id = str(record.get("constraint_id"))
                    if constraint_id in seen_constraint_ids:
                        errors.append("canonical final plan constraint IDs must be unique")
                    seen_constraint_ids.add(constraint_id)
                    canonical_constraint_ids.add(constraint_id)
                    if record.get("provenance") != DERIVED_PLAN_DECISION:
                        errors.append(f"canonical final plan constraint {constraint_id} provenance is required")
                    unknown_requirements = {
                        str(item) for item in record.get("requirement_ids", []) or []
                    } - req_ids
                    if unknown_requirements:
                        errors.append(f"canonical final plan constraint {constraint_id} references an unknown requirement")
                    unknown_obligations = {
                        str(item) for item in record.get("obligation_ids", []) or []
                    } - canonical_obligation_ids
                    if unknown_obligations:
                        errors.append(f"canonical final plan constraint {constraint_id} references an unknown obligation")
                    unknown_nodes = {
                        str(item) for item in record.get("node_ids", []) or []
                    } - known_node_ids
                    if unknown_nodes:
                        errors.append(f"canonical final plan constraint {constraint_id} references an unknown node")
                    if strict_surface_binding:
                        unknown_surfaces = {
                            str(item) for item in record.get("surface_ids", []) or []
                        } - set(surface_by_id)
                        if unknown_surfaces:
                            errors.append(f"canonical final plan constraint {constraint_id} references an unknown surface")
        verifications = value.get("canonical_verification_contracts")
        if not isinstance(verifications, list):
            errors.append("canonical final plan verification contracts are required")
        else:
            verification_ids = [
                str(item.get("verification_id")) for item in verifications
                if isinstance(item, dict) and item.get("verification_id")
            ]
            if len(verification_ids) != len(set(verification_ids)):
                errors.append("canonical final plan verification IDs must be unique")
            canonical_verification_ids.update(verification_ids)
            for item in verifications:
                if not isinstance(item, dict) or not item.get("contract"):
                    errors.append("canonical final plan verification contract is incomplete")
                    continue
                unknown_requirements = {
                    str(value) for value in item.get("requirement_ids", []) or []
                } - req_ids
                unknown_evidence = {
                    str(value) for value in item.get("evidence_ids", []) or []
                } - evidence_ids
                unknown_nodes = {
                    str(value) for value in item.get("node_ids", []) or []
                } - known_node_ids
                if unknown_requirements:
                    errors.append("canonical final plan verification references an unknown requirement")
                if unknown_evidence:
                    errors.append("canonical final plan verification references unknown evidence")
                if unknown_nodes:
                    errors.append("canonical final plan verification references an unknown node")
                if strict_surface_binding:
                    unknown_surfaces = {
                        str(value) for value in item.get("surface_ids", []) or []
                    } - set(surface_by_id)
                    if unknown_surfaces:
                        errors.append("canonical final plan verification references an unknown surface")
        if not isinstance(value.get("impact_references"), list):
            errors.append("canonical final plan impact references are required")
        else:
            seen_impact_ids = set()
            for item in value.get("impact_references", []) or []:
                if not isinstance(item, dict) or not item.get("impact_id"):
                    errors.append("canonical final plan impact reference is incomplete")
                    continue
                impact_id = str(item.get("impact_id"))
                if impact_id in seen_impact_ids:
                    errors.append("canonical final plan impact IDs must be unique")
                seen_impact_ids.add(impact_id)
                unknown_obligations = {
                    str(value) for value in item.get("obligation_ids", []) or []
                } - canonical_obligation_ids
                if unknown_obligations:
                    errors.append(f"canonical final plan impact {impact_id} references an unknown obligation")
                if item.get("node_id") and str(item.get("node_id")) not in known_node_ids:
                    errors.append(f"canonical final plan impact {impact_id} references an unknown node")
                if strict_surface_binding and item.get("surface_id") and str(item.get("surface_id")) not in surface_by_id:
                    errors.append(f"canonical final plan impact {impact_id} references an unknown surface")
    for node in nodes:
        node_id = str(node.get("node_id", ""))
        node_requirements = set(str(item) for item in node.get("requirement_ids", []))
        node_evidence = set(str(item) for item in node.get("evidence_ids", []))
        target_new_surface_ids = {
            str(item) for item in node.get("target_new_surface_proposal_ids", []) if item
        }
        inspect_new_surface_ids = {
            str(item) for item in node.get("inspect_new_surface_proposal_ids", []) if item
        }
        node_new_surface_ids = target_new_surface_ids | inspect_new_surface_ids
        if not node_id:
            errors.append("every plan node requires a node_id")
        if not node.get("done_when"):
            errors.append(f"{node_id}: done_when is required")
        if not node_requirements or not node_requirements.issubset(req_ids):
            errors.append(f"{node_id}: valid requirement responsibility is required")
        if project_mode == EXISTING_PROJECT and not node_new_surface_ids and (
            not node_evidence or not node_evidence.issubset(evidence_ids)
        ):
            errors.append(f"{node_id}: accepted repository evidence is required")
        targets = set(str(item) for item in node.get("candidate_targets", []))
        target_surface_ids = {
            str(item) for item in node.get("target_surface_ids", [])
        }
        if strict_surface_binding:
            if node.get("mutation_required") and not (
                target_surface_ids or target_new_surface_ids
            ):
                errors.append(f"{node_id}: canonical or validated new-surface mutation authority is required")
            if (target_surface_ids or node.get("inspect_surface_ids")) and node_new_surface_ids:
                errors.append(f"{node_id}: plan node has conflicting target authorities")
            if node_new_surface_ids:
                if not node_new_surface_ids.issubset(proposal_by_id):
                    errors.append(f"{node_id}: unknown new-surface proposal authority")
                proposal_requirements = {
                    str(requirement_id)
                    for proposal_id in node_new_surface_ids
                    for requirement_id in proposal_by_id.get(proposal_id, {}).get("requirement_ids", [])
                }
                if not node_requirements.issubset(proposal_requirements):
                    errors.append(f"{node_id}: new-surface proposal does not authorize node requirements")
                if node_evidence or targets:
                    errors.append(f"{node_id}: new-surface authority cannot claim an existing target")
            for surface_id in target_surface_ids | {
                str(item) for item in node.get("inspect_surface_ids", [])
            }:
                surface = surface_by_id.get(surface_id)
                if not surface:
                    errors.append(f"{node_id}: unknown canonical surface")
                    continue
                canonical_path = _normal_path(surface.get("path"))
                if surface_id in target_surface_ids:
                    mutation_surface_ids.add(surface_id)
                    mutation_paths.add(canonical_path)
                if canonical_path and canonical_path not in targets and node.get("mutation_required"):
                    errors.append(f"{node_id}: target path is not derived from canonical surface")
            if node.get("mutation_required"):
                # A node may target more than one canonical surface in future;
                # every target path still has to be a registry-derived path.
                expected_paths = {
                    _normal_path(surface_by_id[item].get("path"))
                    for item in target_surface_ids if item in surface_by_id
                }
                if targets != expected_paths:
                    errors.append(f"{node_id}: mutation targets are not canonical")
            node_interfaces = list(node.get("interface_surface_ids", []) or [])
            for interface_id in node_interfaces:
                interface = surface_by_id.get(str(interface_id))
                if not interface or interface.get("kind") != "INTERFACE":
                    errors.append(f"{node_id}: invalid canonical interface reuse")
                elif str(interface.get("symbol")) not in node.get("interfaces_to_reuse", []):
                    errors.append(f"{node_id}: interface identity is not hydrated")
            inspect_surface_ids = {
                str(item) for item in node.get("inspect_surface_ids", [])
            }
            if node_evidence and (target_surface_ids or inspect_surface_ids):
                allowed_evidence = {
                    evidence_id for surface_id in target_surface_ids | inspect_surface_ids
                    for evidence_id in surface_by_id.get(surface_id, {}).get("evidence_ids", [])
                }
                if not node_evidence.issubset(allowed_evidence):
                    errors.append(f"{node_id}: evidence is not attached to target surface")
        if targets & do_not_touch:
            errors.append(f"{node_id}: mutation target conflicts with do_not_touch")
        if node.get("mutation_required") and not targets and not target_new_surface_ids:
            errors.append(f"{node_id}: mutation responsibility has no approved target")
        if node.get("verification_only") and targets:
            errors.append(f"{node_id}: verification-only responsibility cannot mutate")
        if node.get("provenance") != DERIVED_PLAN_DECISION:
            errors.append(f"{node_id}: plan-decision provenance is required")
        if canonical_representation:
            unknown_constraints = {
                str(item) for item in node.get("constraint_ids", []) or []
            } - canonical_constraint_ids
            unknown_verifications = {
                str(item) for item in node.get("verification_ids", []) or []
            } - canonical_verification_ids
            if unknown_constraints:
                errors.append(f"{node_id}: unknown canonical constraint reference")
            if unknown_verifications:
                errors.append(f"{node_id}: unknown canonical verification reference")
        state_facts = [
            evidence_by_id[item] for item in node_evidence
            if item in evidence_by_id and evidence_by_id[item].get("category") == "CURRENT_STATE_OWNER"
        ]
        if state_facts and _impact_implies_duplicate_owner(node):
            owners = {
                str(item.get("symbol", "")).split(".", 1)[0]
                for item in state_facts if item.get("symbol")
            }
            explicit_duplicate = bool(re.search(
                r"\b(?:add|create|introduce)\b.{0,60}\b(?:paused?|pause state|state)\b",
                str(node.get("goal", "")), re.IGNORECASE,
            ))
            if owners and (
                str(node.get("current_owner", "")) not in owners or explicit_duplicate
            ):
                errors.append(f"{node_id}: ownership conflict is unresolved")
    if strict_surface_binding:
        preservation_ids = {
            str(item.get("surface_id")) for item in value.get("preservation_only_surfaces", [])
            if item.get("surface_id")
        }
        expected_do_not_touch = {
            item for item in do_not_touch_surface_ids
            if item not in mutation_surface_ids
            and item in surface_by_id
            and _normal_path(surface_by_id[item].get("path")) not in mutation_paths
        }
        if do_not_touch_surface_ids != expected_do_not_touch:
            errors.append("do_not_touch surfaces are not deterministically derived")
        expected_paths = {
            _normal_path(surface_by_id[item].get("path"))
            for item in expected_do_not_touch if item in surface_by_id
        }
        if do_not_touch != expected_paths:
            errors.append("do_not_touch paths are not derived from canonical surfaces")
        if mutation_surface_ids.intersection(do_not_touch_surface_ids):
            errors.append("mutation and do_not_touch surface sets must be disjoint")
        if mutation_paths.intersection(do_not_touch):
            errors.append("mutation and do_not_touch paths must be disjoint")
        for test in value.get("tests_to_update_or_add", []) or []:
            test_ids = [str(item) for item in test.get("test_surface_ids", [])]
            test_proposal_ids = {
                str(item) for item in test.get("new_surface_proposal_ids", []) if item
            }
            if test_ids and test_proposal_ids:
                errors.append("test responsibility has conflicting target authorities")
            if test_proposal_ids and not test_proposal_ids.issubset(proposal_by_id):
                errors.append("test responsibility references an invalid new-surface proposal")
            for surface_id in test_ids:
                surface = surface_by_id.get(surface_id)
                if not surface or surface.get("kind") != "TEST":
                    errors.append("test responsibility must reference a TEST surface")
                elif _normal_path(test.get("path")) != _normal_path(surface.get("path")):
                    errors.append("test path is not derived from canonical TEST surface")
    coverage = {str(item.get("requirement_id")): item for item in value.get("coverage", []) if isinstance(item, dict)}
    known_node_ids = {str(item.get("node_id")) for item in nodes}
    for requirement_id in req_ids:
        if requirement_id not in coverage or coverage[requirement_id].get("status") not in COVERAGE_STATUSES:
            errors.append(f"{requirement_id}: coverage record is missing")
        elif coverage[requirement_id].get("status") == "UNASSIGNED":
            errors.append(f"{requirement_id}: active requirement is unassigned")
        elif not set(str(item) for item in coverage[requirement_id].get("node_ids", [] )).issubset(known_node_ids):
            errors.append(f"{requirement_id}: coverage references an unknown plan node")
    reconciliation_summary = value.get("challenger_reconciliation")
    if canonical_representation and isinstance(reconciliation_summary, dict):
        open_blocking_ids = [
            str(item) for item in reconciliation_summary.get(
                "open_blocking_challenge_ids", [],
            ) or [] if item
        ]
        open_blocking_count = reconciliation_summary.get(
            "open_blocking_count", len(open_blocking_ids),
        )
        if open_blocking_count != len(open_blocking_ids):
            errors.append("challenger reconciliation open-blocking count is inconsistent")
        if reconciliation_summary.get("reconciliation_hash") != (
            value.get("upstream_bindings", {}) or {}
        ).get("challenge_reconciliation_hash"):
            errors.append("challenger reconciliation identity is not upstream-bound")
        blocking = open_blocking_ids
    else:
        blocking = [
            item for item in value.get("unresolved_challenges", [])
            if isinstance(item, dict) and item.get("blocking", True)
            and item.get("lifecycle_state") in {None, "OPEN"}
        ]
    if blocking:
        errors.append("unresolved blocking challenge")
    preservation_required = any(_PRESERVE_RE.search(item["text"]) for item in active_requirements(requirements))
    has_canonical_preservation = bool(
        isinstance(canonical_constraints, dict)
        and any(
            isinstance(item, dict) and item.get("text")
            for item in canonical_constraints.get("preservation", []) or []
        )
    )
    if preservation_required and not value.get("preservation_only_surfaces") and not any(
        node.get("preservation_constraints")
        or node.get("local_preservation_constraints")
        or node.get("constraint_ids")
        for node in nodes
    ) and not has_canonical_preservation:
        errors.append("preservation responsibility is missing")
    test_required = any(_TEST_RE.search(item["text"]) for item in active_requirements(requirements))
    current_test = any(item.get("category") == "CURRENT_TEST" for item in bounded_evidence(evidence, 24))
    if test_required and current_test and not value.get("tests_to_update_or_add"):
        errors.append("relevant test responsibility is missing")
    if not value.get("integration_verification"):
        errors.append("integration verification contract is required")
    if _json_size(value) > MAX_PLAN_CHARS:
        errors.append("plan serialized-size bound exceeded")
    semantic_result = evaluate_requirement_obligations(
        value, requirements, evidence, surface_registry, expected_obligation_ledger,
    )
    semantic_by_id = {
        item["requirement_id"]: item for item in semantic_result.get("requirements", [])
    }
    semantic_coverage = semantic_result.get("requirements_covered", 0)
    for requirement_id in sorted(req_ids):
        semantic_record = semantic_by_id.get(requirement_id, {})
        if semantic_record.get("state") != "COVERED":
            uncovered_types = [
                item.get("obligation_type") for item in semantic_record.get("obligations", [])
                if item.get("state") != "COVERED"
            ]
            errors.append(
                f"{requirement_id}: semantic obligations are incomplete ({', '.join(uncovered_types)})"
            )
        if coverage.get(requirement_id, {}).get("semantic_state") not in {None, semantic_record.get("state")}:
            errors.append(f"{requirement_id}: coverage record contradicts semantic evaluation")
    return {
        "valid": not errors,
        "errors": errors[:20],
        "plan_nodes": len(nodes),
        "requirements_covered": sum(
            1 for item in coverage.values() if item.get("status") != "UNASSIGNED"
        ),
        "requirements_unassigned": sum(
            1 for item in coverage.values() if item.get("status") == "UNASSIGNED"
        ),
        "semantic_requirements_covered": semantic_coverage,
        "structural_requirements_covered": sum(
            1 for item in coverage.values() if item.get("status") != "UNASSIGNED"
        ),
        "serialized_chars": _json_size(value),
        "requirement_obligations_created": expected_obligation_ledger.get("obligation_count", 0),
        "behavior_obligations": semantic_result.get("behavior_obligations", 0),
        "behavior_obligations_covered": semantic_result.get("behavior_obligations_covered", 0),
        "behavior_obligations_uncovered": semantic_result.get("behavior_obligations_uncovered", 0),
        "impact_challenges_applicable": int(value.get("impact_challenges_applicable", 0) or 0),
        "impact_challenges_non_applicable": int(value.get("impact_challenges_non_applicable", 0) or 0),
        "challenge_effects_applied": int(value.get("challenge_effects_applied", 0) or 0),
        "challenge_effects_suppressed": int(value.get("challenge_effects_suppressed", 0) or 0),
        "obligation_impacts_synthesized": int(value.get("obligation_impacts_synthesized", 0) or 0),
        "preservation_obligations_closed": sum(
            item.get("state") == "COVERED"
            for record in semantic_result.get("requirements", [])
            for item in record.get("obligations", [])
            if item.get("obligation_type") == "PRESERVATION"
        ),
        "reuse_obligations_closed": sum(
            item.get("state") == "COVERED"
            for record in semantic_result.get("requirements", [])
            for item in record.get("obligations", [])
            if item.get("obligation_type") == "ARCHITECTURE_REUSE"
        ),
        "test_obligations_closed": sum(
            item.get("state") == "COVERED"
            for record in semantic_result.get("requirements", [])
            for item in record.get("obligations", [])
            if item.get("obligation_type") == "TEST"
        ),
        "prohibition_obligations_closed": sum(
            item.get("state") == "COVERED"
            for record in semantic_result.get("requirements", [])
            for item in record.get("obligations", [])
            if item.get("obligation_type") == "PROHIBITION"
        ),
        "semantic_obligation_coverage": semantic_result,
    }


def approval_is_current(plan, approval):
    if not isinstance(plan, dict) or not isinstance(approval, dict):
        return False
    current_hash = plan_content_hash(plan)
    return bool(
        approval.get("approval_status") == "APPROVED"
        and approval.get("plan_id") == plan.get("plan_id")
        and approval.get("plan_hash") == plan.get("plan_hash") == current_hash
    )


def plan_summary(plan):
    value = plan if isinstance(plan, dict) else {}
    changes = []
    for node in value.get("approved_change_nodes", []) or []:
        changes.append({
            "component": node.get("current_owner") or ", ".join(node.get("candidate_targets", []) or node.get("inspect_targets", [])),
            "behavior": _compact(node.get("goal"), 240),
            "mutation_required": bool(node.get("mutation_required")),
            "surface_ids": list(node.get("surface_ids", []) or []),
        })
    return {
        "plan_id": value.get("plan_id"),
        "plan_hash": value.get("plan_hash"),
        "changes": changes[:MAX_PLAN_NODES],
        "preserve": _bounded_strings([
            item for node in value.get("approved_change_nodes", []) or []
            for item in (
                list(node.get("preservation_constraints", []) or [])
                + list(node.get("local_preservation_constraints", []) or [])
            )
        ] + [
            item.get("text") for item in (
                (value.get("canonical_constraints") or {}).get("preservation", [])
                if isinstance(value.get("canonical_constraints"), dict) else []
            ) if isinstance(item, dict)
        ] + [item.get("reason") for item in value.get("preservation_only_surfaces", []) or []], 8, 240),
        "tests": _bounded_strings([
            item.get("path") or "; ".join(item.get("contract", []))
            for item in value.get("tests_to_update_or_add", []) or []
        ], 6, 220),
        "do_not_touch": _bounded_strings(value.get("do_not_touch"), 8, 220),
    }


def approved_plan_node_contract(plan, node_ids=None):
    value = plan if isinstance(plan, dict) else {}
    selected_ids = set(str(item) for item in (node_ids or []))
    nodes = [
        item for item in value.get("approved_change_nodes", []) or []
        if not selected_ids or str(item.get("node_id")) in selected_ids
    ]
    return {
        "plan_id": value.get("plan_id"),
        "plan_hash": value.get("plan_hash"),
        "nodes": [{
            key: copy.deepcopy(node.get(key)) for key in (
                "node_id", "goal", "objective", "requirement_ids", "impact_ids", "evidence_ids",
                "surface_ids", "target_surface_ids", "inspect_surface_ids", "interface_surface_ids",
                "new_surface_proposal_ids", "target_new_surface_proposal_ids",
                "inspect_new_surface_proposal_ids", "new_surface_proposals", "parent_scopes",
                "current_owner", "interfaces_to_reuse", "candidate_targets", "inspect_targets",
                "mutation_required", "verification_only", "local_preservation_constraints",
                "preservation_constraints", "prohibition_constraints", "test_contract", "target_paths",
                "local_test_contract", "done_when", "dependencies", "do_not_touch", "provenance",
                "necessity_status",
            )
        } for node in nodes[:MAX_PLAN_NODES]],
        "integration_verification": _bounded_strings(value.get("integration_verification"), 8, 300),
        "do_not_touch": _bounded_strings(value.get("do_not_touch"), 8, 220),
        "do_not_touch_surface_ids": _bounded_ids(value.get("do_not_touch_surface_ids"), 24),
    }


def decomposition_plan_packet(plan):
    value = plan if isinstance(plan, dict) else {}
    return {
        "plan_id": value.get("plan_id"),
        "plan_hash": value.get("plan_hash"),
        "nodes": [{
            "node_id": item.get("node_id"),
            "goal": _compact(item.get("goal"), 360),
            "objective": _compact(item.get("objective") or item.get("goal"), 360),
            "requirement_ids": list(item.get("requirement_ids", [])),
            "impact_ids": list(item.get("impact_ids", [])),
            "evidence_ids": list(item.get("evidence_ids", [])),
            "surface_ids": list(item.get("surface_ids", [])),
            "target_surface_ids": list(item.get("target_surface_ids", [])),
            "inspect_surface_ids": list(item.get("inspect_surface_ids", [])),
            "new_surface_proposal_ids": list(item.get("new_surface_proposal_ids", [])),
            "target_new_surface_proposal_ids": list(item.get("target_new_surface_proposal_ids", [])),
            "inspect_new_surface_proposal_ids": list(item.get("inspect_new_surface_proposal_ids", [])),
            "parent_scopes": list(item.get("parent_scopes", [])),
            "interface_surface_ids": list(item.get("interface_surface_ids", [])),
            "candidate_targets": list(item.get("candidate_targets", [])),
            "target_paths": list(item.get("target_paths", item.get("candidate_targets", []))),
            "inspect_targets": list(item.get("inspect_targets", [])),
            "mutation_required": bool(item.get("mutation_required")),
            "local_test_contract": _bounded_strings(item.get("local_test_contract"), 4, 220),
            "done_when": _bounded_strings(item.get("done_when"), 4, 220),
        } for item in value.get("approved_change_nodes", []) or []],
        "do_not_touch": list(value.get("do_not_touch", [])),
        "do_not_touch_surface_ids": list(value.get("do_not_touch_surface_ids", [])),
        "integration_verification": _bounded_strings(value.get("integration_verification"), 8, 260),
    }


def _spec_text(spec):
    return " ".join([
        str(spec.get("goal", "")),
        " ".join(str(item) for item in spec.get("done_when", []) or []),
        " ".join(str(item) for item in spec.get("scope_hint", []) or []),
    ])


def _node_text(node):
    return " ".join([
        str(node.get("goal", "")),
        " ".join(str(item) for item in node.get("candidate_targets", []) or []),
        " ".join(str(item) for item in node.get("inspect_targets", []) or []),
        " ".join(str(item) for item in node.get("done_when", []) or []),
    ])


def _path_hint(value):
    text = str(value or "").replace("\\", "/")
    return text if _PATH_RE.search(text) else None


def plan_node_child_specs(plan):
    specs = []
    for node in list((plan or {}).get("approved_change_nodes", []) or [])[:MAX_PLAN_NODES]:
        scope = list(
            node.get("candidate_targets", [])
            or node.get("inspect_targets", [])
            or node.get("parent_scopes", [])
        )
        specs.append({
            "goal": node.get("goal"),
            "done_when": list(node.get("done_when", [])),
            "scope_hint": scope,
            "plan_node_ids": [node.get("node_id")],
            "requirement_ids": list(node.get("requirement_ids", [])),
            "impact_ids": list(node.get("impact_ids", [])),
            "evidence_ids": list(node.get("evidence_ids", [])),
            "new_surface_proposal_ids": list(node.get("new_surface_proposal_ids", [])),
            "verification_only": bool(node.get("verification_only")),
        })
    return specs


def bind_decomposition_to_plan(specs, plan):
    """Project Coordinator children onto approved responsibilities or reject drift."""
    specs = [copy.deepcopy(item) for item in list(specs or []) if isinstance(item, dict)]
    nodes = list((plan or {}).get("approved_change_nodes", []) or [])
    allowed_paths = {
        str(path).replace("\\", "/") for node in nodes
        for path in (
            list(node.get("candidate_targets", []))
            + list(node.get("inspect_targets", []))
            + list(node.get("parent_scopes", []))
        )
    }
    do_not_touch = {str(item).replace("\\", "/") for item in (plan or {}).get("do_not_touch", [])}
    scope_expansions = []
    safe_specs = []
    for spec in specs:
        paths = [_path_hint(item) for item in spec.get("scope_hint", [])]
        paths = [item.replace("\\", "/") for item in paths if item]
        invalid = [item for item in paths if item not in allowed_paths or item in do_not_touch]
        if invalid:
            scope_expansions.extend(invalid)
            continue
        safe_specs.append(spec)
    if not safe_specs:
        safe_specs = plan_node_child_specs(plan)

    assignments = {str(node.get("node_id")): [] for node in nodes}
    for index, spec in enumerate(safe_specs):
        spec_tokens = _tokens(_spec_text(spec))
        scored = []
        for node in nodes:
            node_id = str(node.get("node_id"))
            overlap = len(spec_tokens & _tokens(_node_text(node)))
            if overlap:
                scored.append((-overlap, node_id))
        scored.sort()
        selected = [item[1] for item in scored[:2]]
        if not selected and nodes:
            selected = [str(nodes[index % len(nodes)].get("node_id"))]
        spec["plan_node_ids"] = selected
        for node_id in selected:
            assignments.setdefault(node_id, []).append(index)

    for node_index, node in enumerate(nodes):
        node_id = str(node.get("node_id"))
        if assignments.get(node_id):
            continue
        if not safe_specs:
            safe_specs = plan_node_child_specs(plan)
            break
        target_index = node_index % len(safe_specs)
        safe_specs[target_index].setdefault("plan_node_ids", []).append(node_id)
        assignments.setdefault(node_id, []).append(target_index)

    node_by_id = {str(item.get("node_id")): item for item in nodes}
    for spec in safe_specs:
        selected = [node_by_id[item] for item in spec.get("plan_node_ids", []) if item in node_by_id]
        spec["requirement_ids"] = _bounded_ids([
            value for node in selected for value in node.get("requirement_ids", [])
        ], 16)
        spec["impact_ids"] = _bounded_ids([
            value for node in selected for value in node.get("impact_ids", [])
        ], 12)
        spec["evidence_ids"] = _bounded_ids([
            value for node in selected for value in node.get("evidence_ids", [])
        ], 16)
        spec["new_surface_proposal_ids"] = _bounded_ids([
            value for node in selected for value in node.get("new_surface_proposal_ids", [])
        ], 8)
        spec["verification_only"] = bool(selected) and all(node.get("verification_only") for node in selected)
        approved_scope = _bounded_strings([
            value for node in selected
            for value in (
                list(node.get("candidate_targets", []))
                + list(node.get("inspect_targets", []))
                + list(node.get("parent_scopes", []))
            )
        ], 10, 240)
        spec["scope_hint"] = approved_scope
    covered = {
        item for spec in safe_specs for item in spec.get("plan_node_ids", [])
    }
    return {
        "valid": bool(safe_specs) and set(assignments).issubset(covered),
        "specs": safe_specs,
        "scope_expansions": _bounded_strings(scope_expansions, 12, 240),
        "unassigned_plan_node_ids": sorted(set(assignments) - covered),
    }


def mutation_scope(plan_contract):
    contract = plan_contract if isinstance(plan_contract, dict) else {}
    nodes = list(contract.get("nodes", []) or [])
    return {
        "approved_targets": _bounded_strings([
            item for node in nodes for item in (node.get("candidate_targets", []) or [])
            if node.get("mutation_required")
        ], 16, 240),
        "inspect_only_targets": _bounded_strings([
            item for node in nodes for item in (node.get("inspect_targets", []) or [])
        ], 16, 240),
        "do_not_touch": _bounded_strings(contract.get("do_not_touch"), 16, 240),
        "approved_surface_ids": _bounded_ids([
            item for node in nodes for item in (node.get("target_surface_ids", []) or [])
            if node.get("mutation_required")
        ], 24),
        "approved_new_surface_proposal_ids": _bounded_ids([
            item for node in nodes for item in (node.get("target_new_surface_proposal_ids", []) or [])
            if node.get("mutation_required")
        ], 12),
        "approved_new_surface_parent_scopes": _bounded_strings([
            item for node in nodes for item in (node.get("parent_scopes", []) or [])
            if node.get("mutation_required") and node.get("target_new_surface_proposal_ids")
        ], 12, 240),
        "do_not_touch_surface_ids": _bounded_ids(contract.get("do_not_touch_surface_ids"), 24),
        "verification_only": bool(nodes) and all(node.get("verification_only") for node in nodes),
    }
