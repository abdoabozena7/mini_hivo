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

_CHANGE_RE = re.compile(
    r"\b(?:add|change|create|edit|extend|fix|implement|introduce|migrate|modify|remove|"
    r"replace|support|update)\b", re.IGNORECASE,
)
_PRESERVE_RE = re.compile(
    r"\b(?:do not change|keep|preserve|remain|retain|unchanged|without breaking)\b",
    re.IGNORECASE,
)
_TEST_RE = re.compile(r"\b(?:assert|spec|test|tests|verification|verify)\b", re.IGNORECASE)
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


def build_planner_context(task_brain, requirements, evidence, project_invariants=None):
    """Build the only context the ImpactPlanner may see."""
    reqs = active_requirements(requirements)
    facts = bounded_evidence(evidence)
    slice_value = _task_brain_slice(task_brain)
    context = {
        "task_goal": copy.deepcopy(slice_value.get("task_goal", {})),
        "source_requirements": reqs,
        "user_confirmed_decisions": copy.deepcopy(slice_value.get("user_confirmed_decisions", [])),
        "task_brain_slice": slice_value,
        "project_invariants": _bounded_strings(project_invariants, 8, 360),
        "accepted_repository_evidence": facts,
        "current_owners": copy.deepcopy(slice_value.get("current_owners", [])),
        "current_interfaces": copy.deepcopy(slice_value.get("current_interfaces", [])),
        "current_state_ownership": copy.deepcopy(slice_value.get("current_state_ownership", [])),
        "relevant_tests": copy.deepcopy(slice_value.get("relevant_tests", [])),
        "preservation_constraints": copy.deepcopy(slice_value.get("preservation_constraints", [])),
        "bounds": {
            "max_impact_entries": MAX_IMPACT_ENTRIES,
            "max_requirement_refs_per_impact": MAX_REQUIREMENT_REFS_PER_IMPACT,
            "max_evidence_refs_per_impact": MAX_EVIDENCE_REFS_PER_IMPACT,
            "max_serialized_chars": MAX_PLANNER_CONTEXT_CHARS,
        },
    }
    return _trim_context(context, MAX_PLANNER_CONTEXT_CHARS)


def impact_map_schema():
    entry = {
        "type": "object",
        "properties": {
            "impact_id": {"type": "string"},
            "component": {"type": "string"},
            "path": {"type": "string"},
            "symbols": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "impact_kind": {"type": "string", "enum": list(IMPACT_KINDS)},
            "requirement_ids": {
                "type": "array", "items": {"type": "string"},
                "minItems": 1, "maxItems": MAX_REQUIREMENT_REFS_PER_IMPACT,
            },
            "repository_evidence_ids": {
                "type": "array", "items": {"type": "string"},
                "minItems": 1, "maxItems": MAX_EVIDENCE_REFS_PER_IMPACT,
            },
            "reason": {"type": "string"},
            "existing_owner": {"type": "string"},
            "existing_interfaces_to_reuse": {
                "type": "array", "items": {"type": "string"}, "maxItems": 6,
            },
            "preserve": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "candidate_change": {"type": "string"},
            "local_verification": {
                "type": "array", "items": {"type": "string"}, "maxItems": 6,
            },
            "necessity_status": {"type": "string", "enum": list(NECESSITY_STATUSES)},
        },
        "required": [
            "impact_id", "component", "path", "symbols", "impact_kind", "requirement_ids",
            "repository_evidence_ids", "reason", "existing_owner",
            "existing_interfaces_to_reuse", "preserve", "candidate_change",
            "local_verification", "necessity_status",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
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
        },
        "required": ["task_goal", "impacts", "integration_verification", "insufficient_evidence"],
        "additionalProperties": False,
    }


def normalize_impact_map(candidate):
    candidate = candidate if isinstance(candidate, dict) else {}
    impacts = []
    for index, item in enumerate(list(candidate.get("impacts", []) or [])[:MAX_IMPACT_ENTRIES], 1):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("impact_kind", "")).upper()
        necessity = str(item.get("necessity_status", "CANDIDATE")).upper()
        if kind not in IMPACT_KINDS:
            kind = "INTEGRATION_CHANGE"
        if necessity not in NECESSITY_STATUSES:
            necessity = "CANDIDATE"
        if kind == "PRESERVATION_ONLY":
            necessity = "PRESERVATION_ONLY"
        impacts.append({
            "impact_id": _compact(item.get("impact_id") or f"IMP-{index:03d}", 80),
            "component": _compact(item.get("component") or item.get("path") or "project surface", 180),
            "path": _compact(item.get("path"), 240),
            "symbols": _bounded_strings(item.get("symbols"), 6, 160),
            "impact_kind": kind,
            "requirement_ids": _bounded_ids(item.get("requirement_ids"), MAX_REQUIREMENT_REFS_PER_IMPACT),
            "repository_evidence_ids": _bounded_ids(
                item.get("repository_evidence_ids"), MAX_EVIDENCE_REFS_PER_IMPACT,
            ),
            "reason": _compact(item.get("reason"), MAX_TEXT_CHARS),
            "existing_owner": _compact(item.get("existing_owner"), 180),
            "existing_interfaces_to_reuse": _bounded_strings(
                item.get("existing_interfaces_to_reuse"), 6, 180,
            ),
            "preserve": _bounded_strings(item.get("preserve"), 6, 300),
            "candidate_change": _compact(item.get("candidate_change"), MAX_TEXT_CHARS),
            "local_verification": _bounded_strings(item.get("local_verification"), 6, 300),
            "necessity_status": necessity,
            "provenance": DERIVED_PLAN_DECISION,
        })
    return {
        "version": 1,
        "task_goal": _compact(candidate.get("task_goal"), 1000),
        "impacts": impacts,
        "integration_verification": _bounded_strings(candidate.get("integration_verification"), 10, 320),
        "insufficient_evidence": _bounded_strings(candidate.get("insufficient_evidence"), 6, 320),
        "bounds": {
            "max_impact_entries": MAX_IMPACT_ENTRIES,
            "max_requirement_refs_per_impact": MAX_REQUIREMENT_REFS_PER_IMPACT,
            "max_evidence_refs_per_impact": MAX_EVIDENCE_REFS_PER_IMPACT,
        },
        "provenance": DERIVED_PLAN_DECISION,
    }


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


def validate_impact_map(impact_map, requirements, evidence, project_mode=EXISTING_PROJECT):
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
        if kind not in IMPACT_KINDS:
            errors.append(f"{impact_id}: invalid impact kind")
        if necessity not in NECESSITY_STATUSES:
            errors.append(f"{impact_id}: invalid necessity status")
        req_refs = set(str(ref) for ref in item.get("requirement_ids", []))
        evidence_refs = set(str(ref) for ref in item.get("repository_evidence_ids", []))
        if not req_refs or not req_refs.issubset(requirement_ids):
            errors.append(f"{impact_id}: concrete impact requires valid Source Requirement IDs")
        if project_mode == EXISTING_PROJECT and (
            not evidence_refs or not evidence_refs.issubset(evidence_ids)
        ):
            errors.append(f"{impact_id}: existing-project impact requires accepted repository evidence")
        if len(req_refs) > MAX_REQUIREMENT_REFS_PER_IMPACT:
            errors.append(f"{impact_id}: requirement reference bound exceeded")
        if len(evidence_refs) > MAX_EVIDENCE_REFS_PER_IMPACT:
            errors.append(f"{impact_id}: evidence reference bound exceeded")
        if necessity == "MUST_CHANGE" and (not req_refs or not evidence_refs):
            errors.append(f"{impact_id}: unsupported MUST_CHANGE")
        if kind == "PRESERVATION_ONLY" and necessity != "PRESERVATION_ONLY":
            errors.append(f"{impact_id}: preservation-only surface cannot be MUST_CHANGE")
        if req_refs and (project_mode != EXISTING_PROJECT or evidence_refs):
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


def impact_map_is_valid(candidate, requirements=None, evidence=None, project_mode=EXISTING_PROJECT):
    return validate_impact_map(
        normalize_impact_map(candidate), requirements or [], evidence or [], project_mode,
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


def deterministic_impact_map(task_goal, requirements, evidence):
    """Source/evidence-only fallback when the bounded planner output is invalid."""
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
            "requirement_ids": _bounded_ids(item.get("requirement_ids"), 6),
            "repository_evidence_ids": _bounded_ids(item.get("repository_evidence_ids"), 6),
            "claim": _compact(item.get("claim"), MAX_TEXT_CHARS),
            "proposed_resolution": _compact(item.get("proposed_resolution"), MAX_TEXT_CHARS),
            "blocking": bool(item.get("blocking", challenge_type in BLOCKING_CHALLENGE_TYPES)),
            "source": source,
            "provenance": DERIVED_PLAN_DECISION,
        })
    return result


def build_challenger_context(impact_map, requirements, evidence, task_brain=None):
    brain = _task_brain_slice(task_brain)
    context = {
        "candidate_impact_map": copy.deepcopy(impact_map),
        "source_requirements": active_requirements(requirements),
        "accepted_repository_evidence": bounded_evidence(evidence),
        "preservation_constraints": copy.deepcopy(brain.get("preservation_constraints", [])),
        "current_owners": copy.deepcopy(brain.get("current_owners", [])),
        "current_interfaces": copy.deepcopy(brain.get("current_interfaces", [])),
        "current_state_ownership": copy.deepcopy(brain.get("current_state_ownership", [])),
        "relevant_tests": copy.deepcopy(brain.get("relevant_tests", [])),
        "bounds": {"max_challenges": MAX_CHALLENGES, "challenge_rounds": MAX_CHALLENGE_ROUNDS},
    }
    return _trim_context(context, MAX_CHALLENGER_CONTEXT_CHARS)


def _impact_text(impact):
    return " ".join(str(impact.get(key, "")) for key in (
        "component", "path", "symbols", "reason", "existing_owner", "candidate_change",
        "existing_interfaces_to_reuse", "preserve",
    ))


def _make_challenge(challenge_type, impacts, requirements, evidence, claim, resolution):
    return {
        "challenge_type": challenge_type,
        "impact_ids": _bounded_ids([item.get("impact_id") for item in impacts], 4),
        "requirement_ids": _bounded_ids(requirements, 6),
        "repository_evidence_ids": _bounded_ids(evidence, 6),
        "claim": claim,
        "proposed_resolution": resolution,
        "blocking": True,
    }


def deterministic_challenges(impact_map, requirements, evidence):
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
        if impact.get("necessity_status") == "MUST_CHANGE" and (not linked_requirements or not linked_evidence):
            add(_make_challenge(
                "UNSUPPORTED_NECESSITY", [impact], req_refs, evidence_refs,
                "The MUST_CHANGE claim is not supported by valid requirement and repository evidence references.",
                "Remove the mutation claim or classify the surface as insufficient evidence.",
            ))
        preservation_link = any(_PRESERVE_RE.search(item["text"]) for item in linked_requirements)
        persistence_link = any(item.get("category") == "CURRENT_PERSISTENCE" for item in linked_evidence)
        if impact.get("necessity_status") == "MUST_CHANGE" and preservation_link and persistence_link:
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
        if state_facts and _NEW_OWNER_RE.search(text):
            verified_owners = {
                str(item.get("symbol", "")).split(".", 1)[0]
                for item in state_facts if item.get("symbol")
            }
            proposed_owner = str(impact.get("component") or impact.get("existing_owner") or "")
            if verified_owners and proposed_owner not in verified_owners:
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
        if interface_facts and (_NEW_INTERFACE_RE.search(text) or not reuse):
            add(_make_challenge(
                "INTERFACE_REUSE_MISSED", [impact], req_refs, evidence_refs,
                "A verified current interface is available but the candidate does not clearly reuse it.",
                "Reuse the cited verified interface unless evidence demonstrates it is insufficient.",
            ))

    test_requirements = [item for item in reqs if _TEST_RE.search(item["text"])]
    test_facts = [item for item in facts if item.get("category") == "CURRENT_TEST"]
    test_impacts = [item for item in impacts if item.get("impact_kind") == "TEST_CHANGE"]
    if test_requirements and test_facts and not test_impacts:
        add(_make_challenge(
            "TEST_GAP", [], [item["requirement_id"] for item in test_requirements],
            [item["evidence_id"] for item in test_facts],
            "Behavior changes have no explicit test responsibility despite a test requirement and current test evidence.",
            "Add a focused TEST_CHANGE responsibility using the verified test surface.",
        ))

    covered = {
        str(requirement_id) for item in impacts for requirement_id in item.get("requirement_ids", [])
    }
    for requirement in reqs:
        if requirement["requirement_id"] in covered:
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
            "An active Source Requirement has no impact responsibility.",
            "Add an evidence-supported impact or leave the plan incomplete.",
        ))
    return normalize_challenges({"challenges": challenges}, source="DETERMINISTIC")


def _challenge_relationship_supported(challenge, impacts, req_by_id, evidence_by_id):
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
        return any(
            item.get("necessity_status") == "MUST_CHANGE"
            and (
                not item.get("requirement_ids")
                or not item.get("repository_evidence_ids")
                or any(_PRESERVE_RE.search(req["text"]) for req in requirement_refs)
            )
            for item in impact_refs
        )
    if challenge_type == "REQUIREMENT_GAP":
        covered = {
            str(value) for item in impacts.values() for value in item.get("requirement_ids", [])
        }
        return any(item["requirement_id"] not in covered for item in requirement_refs)
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


def validate_challenges(challenges, impact_map, requirements, evidence):
    impacts = {
        str(item.get("impact_id")): item for item in list((impact_map or {}).get("impacts", []) or [])
        if isinstance(item, dict) and item.get("impact_id")
    }
    req_by_id = {item["requirement_id"]: item for item in active_requirements(requirements)}
    evidence_by_id = {item["evidence_id"]: item for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)}
    accepted, rejected = [], []
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
        if not errors and not _challenge_relationship_supported(
            challenge, impacts, req_by_id, evidence_by_id,
        ):
            errors.append("claimed relationship is not supported by the cited evidence")
        if errors:
            challenge["validation_status"] = "REJECTED"
            challenge["validation_errors"] = errors
            rejected.append(challenge)
        else:
            challenge["validation_status"] = "VALIDATED"
            accepted.append(challenge)
    return {"validated": accepted, "rejected": rejected}


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


def _evidence_impacts_for_gap(challenge, requirements, evidence, start_index):
    req_by_id = {item["requirement_id"]: item for item in active_requirements(requirements)}
    facts = {
        item["evidence_id"]: item for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    }
    selected = [facts[item] for item in challenge.get("repository_evidence_ids", []) if item in facts]
    grouped = {}
    for item in selected:
        grouped.setdefault(item.get("path") or item.get("evidence_id"), []).append(item)
    impacts = []
    for path, records in grouped.items():
        categories = {item.get("category") for item in records}
        kind = "TEST_CHANGE" if "CURRENT_TEST" in categories else "INTEGRATION_CHANGE"
        symbols = _bounded_strings([item.get("symbol") for item in records], 6, 160)
        component = next((item.split(".", 1)[0] for item in symbols if item), path)
        requirement_ids = [item for item in challenge.get("requirement_ids", []) if item in req_by_id]
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


def reconcile_impact_map(impact_map, validated_challenges, requirements, evidence):
    """Apply one bounded deterministic revision; unresolved criticism stays blocking."""
    revised = copy.deepcopy(impact_map if isinstance(impact_map, dict) else {})
    impacts = list(revised.get("impacts", []) or [])
    by_id = {str(item.get("impact_id")): item for item in impacts}
    evidence_by_id = {
        item["evidence_id"]: item for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    }
    req_by_id = {item["requirement_id"]: item for item in active_requirements(requirements)}
    resolved, unresolved = [], []
    for challenge in list(validated_challenges or [])[:MAX_CHALLENGES]:
        challenge_type = challenge.get("challenge_type")
        targets = [by_id[item] for item in challenge.get("impact_ids", []) if item in by_id]
        applied = False
        if challenge_type in {"UNSUPPORTED_NECESSITY", "UNRELATED_CHANGE"}:
            for target in targets:
                linked = [
                    evidence_by_id[item] for item in target.get("repository_evidence_ids", [])
                    if item in evidence_by_id
                ]
                preservation = (
                    target.get("impact_kind") == "PRESERVATION_ONLY"
                    or any(item.get("category") == "CURRENT_PERSISTENCE" for item in linked)
                    and (
                        bool(target.get("preserve"))
                        or any(
                            item in req_by_id and _PRESERVE_RE.search(req_by_id[item]["text"])
                            for item in challenge.get("requirement_ids", [])
                        )
                    )
                )
                if preservation:
                    target["impact_kind"] = "PRESERVATION_ONLY"
                    target["necessity_status"] = "PRESERVATION_ONLY"
                    target["candidate_change"] = "No mutation planned; retain this verified preservation surface."
                    target["preserve"] = _bounded_strings(
                        list(target.get("preserve", [])) + [
                            req_by_id[item]["text"] for item in challenge.get("requirement_ids", [])
                            if item in req_by_id and _PRESERVE_RE.search(req_by_id[item]["text"])
                        ],
                        6, 300,
                    )
                else:
                    target["necessity_status"] = "INSUFFICIENT_EVIDENCE"
                applied = True
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
                    target["candidate_change"] = _compact(
                        challenge.get("proposed_resolution")
                        or "Use the verified owner; do not introduce duplicate state ownership.",
                    )
                    target["preserve"] = _bounded_strings(
                        list(target.get("preserve", [])) + [f"authoritative state ownership remains with {owner}"],
                        6, 300,
                    )
                    applied = True
        elif challenge_type == "INTERFACE_REUSE_MISSED":
            for target in targets:
                interfaces = [
                    evidence_by_id[item].get("symbol")
                    for item in target.get("repository_evidence_ids", [])
                    if item in evidence_by_id and evidence_by_id[item].get("category") == "CURRENT_INTERFACE"
                ]
                if interfaces:
                    target["existing_interfaces_to_reuse"] = _bounded_strings(
                        list(target.get("existing_interfaces_to_reuse", [])) + interfaces, 6, 180,
                    )
                    target["candidate_change"] = _compact(
                        challenge.get("proposed_resolution") or "Reuse the verified current interface.",
                    )
                    applied = True
        elif challenge_type in {"TEST_GAP", "MISSING_IMPACT", "REQUIREMENT_GAP", "DEPENDENCY_GAP"}:
            additions = _evidence_impacts_for_gap(
                challenge, requirements, evidence, len(impacts) + 1,
            )
            for addition in additions:
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
        record = copy.deepcopy(challenge)
        record["resolution_status"] = "RESOLVED" if applied else "UNRESOLVED"
        (resolved if applied else unresolved).append(record)
    revised["impacts"] = impacts[:MAX_IMPACT_ENTRIES]
    revised["challenge_rounds"] = 1
    revised["revision_rounds"] = 1 if validated_challenges else 0
    return normalize_impact_map(revised), resolved, unresolved


def _requirement_change_required(requirement_ids, req_by_id):
    return any(_CHANGE_RE.search(req_by_id[item]["text"]) for item in requirement_ids if item in req_by_id)


def _surface_record(impact):
    return {
        "component": impact.get("component"),
        "path": impact.get("path"),
        "symbols": list(impact.get("symbols", [])),
        "requirement_ids": list(impact.get("requirement_ids", [])),
        "evidence_ids": list(impact.get("repository_evidence_ids", [])),
        "reason": impact.get("reason"),
        "mutation_planned": False,
        "provenance": DERIVED_PLAN_DECISION,
    }


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


def build_minimal_change_plan(impact_map, requirements, evidence, resolved_challenges=None,
                              unresolved_challenges=None, project_mode=EXISTING_PROJECT):
    reqs = active_requirements(requirements)
    req_by_id = {item["requirement_id"]: item for item in reqs}
    evidence_by_id = {
        item["evidence_id"]: item for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    }
    impacts = list((impact_map or {}).get("impacts", []) or [])
    preservation, nodes, tests = [], [], []
    interface_reuse = []
    for impact in impacts:
        req_ids = [item for item in impact.get("requirement_ids", []) if item in req_by_id]
        evidence_ids = [item for item in impact.get("repository_evidence_ids", []) if item in evidence_by_id]
        if impact.get("necessity_status") == "INSUFFICIENT_EVIDENCE":
            continue
        if impact.get("impact_kind") == "PRESERVATION_ONLY" or impact.get("necessity_status") == "PRESERVATION_ONLY":
            preservation.append(_surface_record(impact))
            continue
        if not req_ids or (project_mode == EXISTING_PROJECT and not evidence_ids):
            continue
        kind = impact.get("impact_kind")
        mutation_required = impact.get("necessity_status") == "MUST_CHANGE"
        if impact.get("necessity_status") == "CANDIDATE":
            mutation_required = (
                kind in {"BEHAVIOR_CHANGE", "INTEGRATION_CHANGE", "TEST_CHANGE"}
                and _requirement_change_required(req_ids, req_by_id)
            )
        if kind in {"INTERFACE_REUSE", "CROSS_CUTTING_VERIFICATION"}:
            mutation_required = False
        interfaces = _bounded_strings(impact.get("existing_interfaces_to_reuse"), 6, 180)
        interface_reuse.extend(interfaces)
        path = str(impact.get("path", ""))
        node = {
            "node_id": f"NODE-{len(nodes) + 1:03d}",
            "goal": _compact(impact.get("candidate_change") or impact.get("reason"), 700),
            "requirement_ids": req_ids,
            "impact_ids": [impact.get("impact_id")],
            "evidence_ids": evidence_ids,
            "current_owner": _compact(impact.get("existing_owner"), 180),
            "interfaces_to_reuse": interfaces,
            "candidate_targets": [path] if path and mutation_required else [],
            "inspect_targets": [path] if path and not mutation_required else [],
            "mutation_required": bool(mutation_required),
            "verification_only": not mutation_required,
            "preservation_constraints": _bounded_strings(impact.get("preserve"), 6, 300),
            "local_test_contract": _bounded_strings(impact.get("local_verification"), 6, 300),
            "done_when": _bounded_strings(
                impact.get("local_verification")
                or [req_by_id[item]["text"] for item in req_ids], 6, 300,
            ),
            "dependencies": [],
            "do_not_touch": [],
            "impact_kind": kind,
            "necessity_status": impact.get("necessity_status"),
            "provenance": DERIVED_PLAN_DECISION,
        }
        nodes.append(node)
        if kind == "TEST_CHANGE":
            tests.append({
                "node_id": node["node_id"], "path": path,
                "requirement_ids": req_ids, "evidence_ids": evidence_ids,
                "contract": list(node["local_test_contract"] or node["done_when"]),
                "provenance": DERIVED_PLAN_DECISION,
            })
        if len(nodes) >= MAX_PLAN_NODES:
            break

    do_not_touch = _bounded_strings(
        [item.get("path") for item in preservation if item.get("path")], MAX_PLAN_NODES, 240,
    )
    test_nodes = [item["node_id"] for item in nodes if item.get("impact_kind") == "TEST_CHANGE"]
    behavior_nodes = [item["node_id"] for item in nodes if item.get("impact_kind") != "TEST_CHANGE"]
    all_test_contracts = _bounded_strings(
        [value for item in tests for value in item.get("contract", [])], 6, 300,
    )
    for node in nodes:
        node["do_not_touch"] = list(do_not_touch)
        if node.get("impact_kind") == "TEST_CHANGE":
            node["dependencies"] = behavior_nodes[:4]
        elif all_test_contracts:
            node["local_test_contract"] = _bounded_strings(
                list(node.get("local_test_contract", [])) + all_test_contracts, 6, 300,
            )

    coverage = []
    for requirement in reqs:
        requirement_id = requirement["requirement_id"]
        linked_nodes = [item for item in nodes if requirement_id in item.get("requirement_ids", [])]
        linked_preservation = [
            item for item in preservation if requirement_id in item.get("requirement_ids", [])
        ]
        if any(item.get("impact_kind") == "TEST_CHANGE" for item in linked_nodes):
            status = "COVERED_BY_TEST"
        elif any(item.get("mutation_required") for item in linked_nodes):
            status = "COVERED_BY_CHANGE"
        elif linked_preservation:
            status = "COVERED_BY_PRESERVATION"
        elif linked_nodes:
            status = "CROSS_CUTTING"
        else:
            status = "UNASSIGNED"
        coverage.append({
            "requirement_id": requirement_id,
            "status": status,
            "node_ids": [item["node_id"] for item in linked_nodes],
            "impact_ids": _bounded_ids([
                value for item in linked_nodes for value in item.get("impact_ids", [])
            ], 6),
            "provenance": DERIVED_PLAN_DECISION,
        })

    integration = _bounded_strings((impact_map or {}).get("integration_verification"), 10, 320)
    for item in preservation:
        if item.get("reason"):
            integration = _bounded_strings(
                integration + [f"Preserve without mutation: {item['reason']}"], 10, 320,
            )
    if tests:
        integration = _bounded_strings(integration + ["Run the approved relevant test contracts."], 10, 320)
    if not integration:
        integration = ["Verify every approved responsibility and preservation constraint after fan-in."]

    plan = {
        "version": 1,
        "task_goal": _compact((impact_map or {}).get("task_goal"), 1000),
        "project_mode": project_mode,
        "requirements": reqs,
        "approved_change_nodes": nodes,
        "preservation_only_surfaces": preservation[:MAX_PLAN_NODES],
        "interfaces_to_reuse": _bounded_strings(interface_reuse, 10, 180),
        "tests_to_update_or_add": tests[:MAX_PLAN_NODES],
        "integration_verification": integration,
        "do_not_touch": do_not_touch,
        "resolved_challenges": list(resolved_challenges or [])[:MAX_CHALLENGES],
        "unresolved_challenges": list(unresolved_challenges or [])[:MAX_CHALLENGES],
        "coverage": coverage,
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
    return finalize_plan_identity(plan)


def validate_change_plan(plan, requirements, evidence, project_mode=EXISTING_PROJECT):
    value = plan if isinstance(plan, dict) else {}
    errors = []
    req_ids = {item["requirement_id"] for item in active_requirements(requirements)}
    evidence_ids = {item["evidence_id"] for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)}
    evidence_by_id = {
        item["evidence_id"]: item for item in bounded_evidence(evidence, MAX_IMPACT_ENTRIES * 2)
    }
    nodes = list(value.get("approved_change_nodes", []) or [])
    if len(nodes) > MAX_PLAN_NODES:
        errors.append("plan node bound exceeded")
    if value.get("plan_hash") != plan_content_hash(value):
        errors.append("plan hash does not match plan content")
    if value.get("plan_id") != f"PLAN-{str(value.get('plan_hash', ''))[:12].upper()}":
        errors.append("plan ID does not match plan hash")
    do_not_touch = set(str(item) for item in value.get("do_not_touch", []))
    for node in nodes:
        node_id = str(node.get("node_id", ""))
        node_requirements = set(str(item) for item in node.get("requirement_ids", []))
        node_evidence = set(str(item) for item in node.get("evidence_ids", []))
        if not node_id:
            errors.append("every plan node requires a node_id")
        if not node.get("done_when"):
            errors.append(f"{node_id}: done_when is required")
        if not node_requirements or not node_requirements.issubset(req_ids):
            errors.append(f"{node_id}: valid requirement responsibility is required")
        if project_mode == EXISTING_PROJECT and (not node_evidence or not node_evidence.issubset(evidence_ids)):
            errors.append(f"{node_id}: accepted repository evidence is required")
        targets = set(str(item) for item in node.get("candidate_targets", []))
        if targets & do_not_touch:
            errors.append(f"{node_id}: mutation target conflicts with do_not_touch")
        if node.get("mutation_required") and not targets:
            errors.append(f"{node_id}: mutation responsibility has no approved target")
        if node.get("verification_only") and targets:
            errors.append(f"{node_id}: verification-only responsibility cannot mutate")
        if node.get("provenance") != DERIVED_PLAN_DECISION:
            errors.append(f"{node_id}: plan-decision provenance is required")
        state_facts = [
            evidence_by_id[item] for item in node_evidence
            if item in evidence_by_id and evidence_by_id[item].get("category") == "CURRENT_STATE_OWNER"
        ]
        if state_facts and _NEW_OWNER_RE.search(str(node.get("goal", ""))):
            owners = {
                str(item.get("symbol", "")).split(".", 1)[0]
                for item in state_facts if item.get("symbol")
            }
            if owners and str(node.get("current_owner", "")) not in owners:
                errors.append(f"{node_id}: ownership conflict is unresolved")
    coverage = {str(item.get("requirement_id")): item for item in value.get("coverage", []) if isinstance(item, dict)}
    for requirement_id in req_ids:
        if requirement_id not in coverage or coverage[requirement_id].get("status") not in COVERAGE_STATUSES:
            errors.append(f"{requirement_id}: coverage record is missing")
        elif coverage[requirement_id].get("status") == "UNASSIGNED":
            errors.append(f"{requirement_id}: active requirement is unassigned")
    blocking = [
        item for item in value.get("unresolved_challenges", [])
        if isinstance(item, dict) and item.get("blocking", True)
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
        "serialized_chars": _json_size(value),
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
                "node_id", "goal", "requirement_ids", "impact_ids", "evidence_ids",
                "current_owner", "interfaces_to_reuse", "candidate_targets", "inspect_targets",
                "mutation_required", "verification_only", "preservation_constraints",
                "local_test_contract", "done_when", "dependencies", "do_not_touch", "provenance",
                "necessity_status",
            )
        } for node in nodes[:MAX_PLAN_NODES]],
        "integration_verification": _bounded_strings(value.get("integration_verification"), 8, 300),
        "do_not_touch": _bounded_strings(value.get("do_not_touch"), 8, 220),
    }


def decomposition_plan_packet(plan):
    value = plan if isinstance(plan, dict) else {}
    return {
        "plan_id": value.get("plan_id"),
        "plan_hash": value.get("plan_hash"),
        "nodes": [{
            "node_id": item.get("node_id"),
            "goal": _compact(item.get("goal"), 360),
            "requirement_ids": list(item.get("requirement_ids", [])),
            "impact_ids": list(item.get("impact_ids", [])),
            "evidence_ids": list(item.get("evidence_ids", [])),
            "candidate_targets": list(item.get("candidate_targets", [])),
            "inspect_targets": list(item.get("inspect_targets", [])),
            "mutation_required": bool(item.get("mutation_required")),
            "local_test_contract": _bounded_strings(item.get("local_test_contract"), 4, 220),
            "done_when": _bounded_strings(item.get("done_when"), 4, 220),
        } for item in value.get("approved_change_nodes", []) or []],
        "do_not_touch": list(value.get("do_not_touch", [])),
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
        scope = list(node.get("candidate_targets", []) or node.get("inspect_targets", []))
        specs.append({
            "goal": node.get("goal"),
            "done_when": list(node.get("done_when", [])),
            "scope_hint": scope,
            "plan_node_ids": [node.get("node_id")],
            "requirement_ids": list(node.get("requirement_ids", [])),
            "impact_ids": list(node.get("impact_ids", [])),
            "evidence_ids": list(node.get("evidence_ids", [])),
            "verification_only": bool(node.get("verification_only")),
        })
    return specs


def bind_decomposition_to_plan(specs, plan):
    """Project Coordinator children onto approved responsibilities or reject drift."""
    specs = [copy.deepcopy(item) for item in list(specs or []) if isinstance(item, dict)]
    nodes = list((plan or {}).get("approved_change_nodes", []) or [])
    allowed_paths = {
        str(path).replace("\\", "/") for node in nodes
        for path in list(node.get("candidate_targets", [])) + list(node.get("inspect_targets", []))
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
        spec["verification_only"] = bool(selected) and all(node.get("verification_only") for node in selected)
        approved_scope = _bounded_strings([
            value for node in selected
            for value in list(node.get("candidate_targets", [])) + list(node.get("inspect_targets", []))
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
        "verification_only": bool(nodes) and all(node.get("verification_only") for node in nodes),
    }
