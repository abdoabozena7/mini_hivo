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
    "CURRENT_TEST", "ENTRYPOINT", "REPOSITORY_SURFACE",
)
DISPOSITIONS = (
    "MUST_CHANGE", "INTERFACE_REUSE", "TEST_CHANGE", "PRESERVATION_ONLY",
    "VERIFY_ONLY", "INSUFFICIENT_EVIDENCE",
)
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
        result.append({
            "requirement_id": requirement_id,
            "text": _compact(text, 700),
            "provenance": str(item.get("provenance") or USER_STATED),
            "status": "active",
        })
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


def build_requirement_obligation_ledger(requirements):
    """Classify active source requirements into deterministic obligations."""
    records = []
    for requirement in active_requirements(requirements):
        text = requirement["text"]
        obligation_types = []
        is_test = bool(_TEST_RE.search(text))
        is_preservation = bool(_PRESERVE_RE.search(text))
        is_reuse = bool(_REUSE_RE.search(text))
        is_prohibition = bool(_PROHIBITION_RE.search(text))
        # A test-only sentence is not a product behavior mutation merely
        # because it contains "add" or "update".  A compound sentence such
        # as "add export and tests" retains both obligations.
        non_test_terms = _domain_tokens(text) - {
            "assert", "coverage", "spec", "test", "tests", "verification", "verify",
        }
        behavior = bool(_CHANGE_RE.search(text)) and not (is_test and not non_test_terms)
        if behavior:
            obligation_types.append("BEHAVIOR_CHANGE")
        if is_reuse:
            obligation_types.append("ARCHITECTURE_REUSE")
        if is_preservation:
            obligation_types.append("PRESERVATION")
        if is_test:
            obligation_types.append("TEST")
        if is_prohibition:
            obligation_types.append("PROHIBITION")
        if _CROSS_CUTTING_RE.search(text):
            obligation_types.append("CROSS_CUTTING")
        if not obligation_types:
            # An active declarative requirement still needs a concrete
            # semantic home.  Treat it as behavior unless it is explicitly a
            # non-mutating constraint.
            obligation_types.append("BEHAVIOR_CHANGE")
        records.append({
            "requirement_id": requirement["requirement_id"],
            "text": text,
            "obligation_types": [
                item for item in REQUIREMENT_OBLIGATION_TYPES if item in obligation_types
            ],
            "source_provenance": requirement.get("provenance", USER_STATED),
            "classification_provenance": DERIVED_PLAN_DECISION,
        })
    return {
        "version": 1,
        "requirements": records,
        "obligation_count": sum(len(item["obligation_types"]) for item in records),
        "bounds": {"max_requirements": len(records), "allowed_types": list(REQUIREMENT_OBLIGATION_TYPES)},
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
    return {
        "version": 1,
        "requirements": [{
            "requirement_id": item.get("requirement_id"),
            "obligation_types": list(item.get("obligation_types", [])),
            "source_provenance": item.get("source_provenance", USER_STATED),
            "classification_provenance": DERIVED_PLAN_DECISION,
        } for item in records],
        "obligation_count": sum(len(item.get("obligation_types", [])) for item in records),
        "provenance": DERIVED_PLAN_DECISION,
    }


def bounded_evidence(evidence, max_items=12):
    """Keep semantic Stage 2 facts and hashes, never raw source support."""
    result = []
    for item in list(evidence or [])[:max_items]:
        if not isinstance(item, dict) or not item.get("evidence_id"):
            continue
        result.append({
            "evidence_id": str(item.get("evidence_id")),
            "category": _compact(item.get("category"), 80),
            "fact": _compact(item.get("fact"), 300),
            "path": _compact(item.get("path"), 240),
            "symbol": _compact(item.get("symbol"), 180),
            "line_start": item.get("line_start"),
            "line_end": item.get("line_end"),
            "file_sha256": _compact(item.get("file_sha256"), 80),
            "provenance": REPOSITORY_EVIDENCE,
        })
    return result


def _surface_symbol_base(symbol):
    """Return the owner symbol portion of a verified symbol."""
    text = str(symbol or "").strip()
    if not text:
        return ""
    return re.split(r"::|[.#:]", text, maxsplit=1)[0]


def _surface_role(category, symbol="", fact=""):
    category = str(category or "").upper()
    text = f"{symbol} {fact}".casefold()
    if category == "CURRENT_TEST":
        return "CURRENT_TEST"
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
        "OWNER": 2,
        "INTERFACE": 3,
        "PERSISTENCE_OWNER": 4,
        "CURRENT_TEST": 5,
        "ENTRYPOINT": 6,
        "REPOSITORY_SURFACE": 7,
    }
    return (
        role_order.get(role, 9),
        str(group.get("path") or "").casefold(),
        str(group.get("symbol") or "").casefold(),
        str(group.get("first_evidence_id") or "").casefold(),
    )


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
            "role": _surface_role(first.get("category"), first.get("symbol"), first.get("fact")),
            "path": str(first.get("path") or "").replace("\\", "/"),
            "symbol": _surface_symbol_base(first.get("symbol")),
            "verified_fact": _compact(" ".join(item.get("fact", "") for item in records), 360),
            "evidence_ids": _bounded_ids(
                [item.get("evidence_id") for item in records], MAX_SURFACE_EVIDENCE_IDS,
            ),
            "first_evidence_id": records[0].get("evidence_id"),
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
        })
    for records in simple_groups.values():
        first = records[0]
        category = str(first.get("category") or "").upper()
        groups.append({
            "kind": _surface_kind(category),
            "role": _surface_role(category, first.get("symbol"), first.get("fact")),
            "path": str(first.get("path") or "").replace("\\", "/"),
            "symbol": str(first.get("symbol") or ""),
            "verified_fact": _compact(" ".join(item.get("fact", "") for item in records), 360),
            "evidence_ids": _bounded_ids(
                [item.get("evidence_id") for item in records], MAX_SURFACE_EVIDENCE_IDS,
            ),
            "first_evidence_id": records[0].get("evidence_id"),
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
        req_ids = []
        for requirement in reqs:
            if terms.intersection(_tokens(requirement.get("text"))):
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
            # A requirement record is already the mandatory user statement;
            # retain its source identity only when it also carries a durable
            # authority/evidence identity.
            if not text and not refs and not path and not symbol:
                continue
            # A durable fact commonly appears in both ``current_authority``
            # and ``current_verified_facts``.  Keep the distinct source refs
            # and authority classes internally, but render one bounded
            # model-facing statement for the shared semantic obligation.
            key = (text.casefold(), path.casefold(), symbol.casefold())
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
        optional_items = _planner_optional_items(payload)
        mandatory_payload = _planner_mandatory_payload(payload, optional_items)
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
            for item in payload.get("confirmed_conflicts", [])
            if isinstance(item, dict) and item.get("conflict_id")
        )
        mandatory_ids.extend(
            f"AUTHORITY-{index:03d}"
            for index, item in enumerate(payload.get("current_authority", []), 1)
            if isinstance(item, dict)
        )
        if include_role_authority:
            mandatory_ids.extend(["PLANNING_PROVENANCE", "CURRENT_VS_DESIRED"])
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
        )
        # Structural errors must be reflected in the exact model packet too;
        # the marker is never appended after the packet was audited.
        return (
            role_packet.get("payload", {}), seeds, seed_validation,
            role_packet.get("rendered_chars", 0), role_packet,
            optional_items, mandatory_payload, mandatory_ids,
        )

    (
        payload, seeds, seed_validation, packet_chars, role_packet,
        optional_items, mandatory_payload, mandatory_ids,
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
            optional_items, mandatory_payload, mandatory_ids,
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


def normalize_impact_map(candidate, authoritative=False):
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


def validate_planner_output(candidate, requirements=None, allow_legacy=False,
                            impact_seeds=None):
    """Validate the response envelope while retaining usable decisions.

    Optional-field and per-decision semantic validation happens during seed
    binding/hydration.  This pre-call validator only needs one structurally
    usable decision to keep a mixed response from triggering whole-response
    brittleness.
    """
    value = candidate if isinstance(candidate, dict) else {}
    if "impacts" not in value and value.get("impact_id"):
        impacts = [value]
    else:
        impacts = value.get("impacts", [])
    if not isinstance(impacts, (list, tuple)) or not impacts:
        return False
    if len(impacts) > MAX_IMPACT_ENTRIES:
        return False
    req_ids = {item["requirement_id"] for item in active_requirements(requirements or [])}
    seed_ids = {
        normalize_impact_id(item.get("impact_id"))
        for item in list(impact_seeds or []) if isinstance(item, dict)
    }
    usable = 0
    for item in list(impacts):
        if not isinstance(item, dict):
            continue
        impact_id = str(item.get("impact_id") or "").strip()
        if not impact_id:
            continue
        refs = _list_value(item.get("requirement_ids"))
        if not refs:
            continue
        disposition = str(item.get("disposition", "")).upper().strip()
        if not disposition and allow_legacy:
            disposition = _disposition_for_impact(item)
        if disposition not in DISPOSITIONS:
            continue
        action = item.get("action") or item.get("reason") or item.get("candidate_change")
        if not isinstance(action, str) or not action.strip():
            continue
        normalized_id = normalize_impact_id(impact_id)
        if seed_ids and not seed_ids.intersection({normalized_id}) and not _list_value(
            item.get("new_surface_proposal_ids")
        ):
            continue
        # Unknown requirement IDs are deliberately left for per-decision
        # relationship validation, so a mixed response can still proceed.
        if req_ids and not any(str(ref) for ref in refs):
            continue
        usable += 1
    if _forbidden_context_key(value):
        return False
    return usable > 0


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
                            render=None, base_render=None, verified_planning_context=None):
    """Build a complete review packet using the exact role renderer."""
    max_chars = MAX_CHALLENGER_CONTEXT_CHARS if max_chars is None else max_chars
    max_chars = max(1, int(max_chars))
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
    optional_items = _challenger_optional_items(packet)
    mandatory_payload = _challenger_mandatory_payload(packet)
    mandatory_ids = [
        "CANDIDATE_IMPACT_MAP",
        *[f"IMPACT-{item.get('impact_id')}" for item in impacts if item.get("impact_id")],
        *[f"REQUIREMENT-{item.get('requirement_id')}" for item in _planner_requirement_projection(requirements)],
        *[f"SURFACE-{item}" for item in selected_surface_ids],
        "PRESERVATION_CONSTRAINTS",
    ]
    if include_role_authority:
        mandatory_ids.extend(["CURRENT_AUTHORITY", "CONFIRMED_CONFLICTS", "PLANNING_PROVENANCE"])

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
    for field, priority in (("integration_verification", 40), ("insufficient_evidence", 30)):
        for index, item in enumerate(list(candidate.get(field, []) or [])):
            add(f"candidate_{field}", priority, ("candidate_impact_map", field), item, index)

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
    optional_items = _revision_optional_items(value)
    mandatory_payload = _revision_mandatory_payload(value)
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
        )
        packet = role_packet.get("payload", packet)
        packet_chars = role_packet.get("rendered_chars", packet_chars)
        complete = False
    observability = {
        "packet_chars": packet_chars,
        "payload_chars": len(_compact_json(packet)),
        "estimated_tokens": _estimated_tokens(role_packet.get("rendered_packet", _compact_json(packet))),
        "packet_complete": complete,
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
                covered = any(_PROHIBITION_RE.search(str(item)) for item in constraints)
                if covered:
                    support.extend(_bounded_strings(constraints, 3, 120))
            elif obligation_type == "CROSS_CUTTING":
                covered = bool(linked and integration)
                if covered:
                    support.extend(integration[:2])
            type_records.append({
                "obligation_type": obligation_type,
                "state": "COVERED" if covered else "UNCOVERED",
                "support": _bounded_strings(support, 6, 180),
            })
        result.append({
            "requirement_id": requirement_id,
            "obligation_types": list(obligation.get("obligation_types", [])),
            "obligations": type_records,
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
                         obligation_ledger=None, task_goal=None, task_brain=None):
    """Apply one bounded deterministic revision while conserving obligations."""
    revised = copy.deepcopy(impact_map if isinstance(impact_map, dict) else {})
    impacts = list(revised.get("impacts", []) or [])
    by_id = {str(item.get("impact_id")): item for item in impacts}
    evidence_by_id = {
        item["evidence_id"]: item for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    }
    req_by_id = {item["requirement_id"]: item for item in active_requirements(requirements)}
    surface_by_id = canonical_surface_by_id(surface_registry) if surface_registry else {}
    obligation_ledger = obligation_ledger or build_requirement_obligation_ledger(requirements)
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
    normalized["requirement_obligation_ledger"] = copy.deepcopy(obligation_ledger)
    normalized["semantic_obligation_coverage"] = semantic
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


def _fit_plan_to_serialized_bound(plan):
    """Trim only redundant compatibility projections when the plan is tight."""
    value = plan if isinstance(plan, dict) else {}
    # These fields are retained in ordinary plans for compatibility, but are
    # exact projections of canonical fields already present in the node.  A
    # newly confirmed requirement can otherwise push an otherwise valid plan
    # a few characters beyond the fixed Stage 3 bound.
    optional_node_fields = (
        "objective", "target_paths", "test_contract", "new_surface_proposals",
        "parent_scopes", "dependencies", "inspect_targets",
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
                              task_goal=None):
    reqs = active_requirements(requirements)
    obligation_ledger = obligation_ledger or (
        (impact_map or {}).get("requirement_obligation_ledger")
        or build_requirement_obligation_ledger(reqs)
    )
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
        "requirement_obligation_ledger": compact_requirement_obligation_ledger(obligation_ledger),
        "semantic_obligation_coverage": semantic,
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
                         authoritative_task_goal=None):
    value = plan if isinstance(plan, dict) else {}
    errors = []
    expected_obligation_ledger = obligation_ledger or build_requirement_obligation_ledger(requirements)
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
    if value.get("requirement_obligation_ledger") != compact_requirement_obligation_ledger(
        expected_obligation_ledger
    ):
        errors.append("requirement obligation ledger is missing or not authoritative")
    do_not_touch = set(str(item) for item in value.get("do_not_touch", []))
    do_not_touch_surface_ids = {
        str(item) for item in value.get("do_not_touch_surface_ids", [])
    }
    mutation_surface_ids = set()
    mutation_paths = set()
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
    blocking = [
        item for item in value.get("unresolved_challenges", [])
        if isinstance(item, dict) and item.get("blocking", True)
        and item.get("lifecycle_state") in {None, "OPEN"}
    ]
    if blocking:
        errors.append("unresolved blocking challenge")
    preservation_required = any(_PRESERVE_RE.search(item["text"]) for item in active_requirements(requirements))
    if preservation_required and not value.get("preservation_only_surfaces") and not any(
        node.get("preservation_constraints") for node in nodes
    ):
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
            for item in node.get("preservation_constraints", [])
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
            item for node in nodes for item in node.get("candidate_targets", [])
            if node.get("mutation_required")
        ], 16, 240),
        "inspect_only_targets": _bounded_strings([
            item for node in nodes for item in node.get("inspect_targets", [])
        ], 16, 240),
        "do_not_touch": _bounded_strings(contract.get("do_not_touch"), 16, 240),
        "approved_surface_ids": _bounded_ids([
            item for node in nodes for item in node.get("target_surface_ids", [])
            if node.get("mutation_required")
        ], 24),
        "approved_new_surface_proposal_ids": _bounded_ids([
            item for node in nodes for item in node.get("target_new_surface_proposal_ids", [])
            if node.get("mutation_required")
        ], 12),
        "approved_new_surface_parent_scopes": _bounded_strings([
            item for node in nodes for item in node.get("parent_scopes", [])
            if node.get("mutation_required") and node.get("target_new_surface_proposal_ids")
        ], 12, 240),
        "do_not_touch_surface_ids": _bounded_ids(contract.get("do_not_touch_surface_ids"), 24),
        "verification_only": bool(nodes) and all(node.get("verification_only") for node in nodes),
    }
