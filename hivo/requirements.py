"""Bounded source-requirement and clarification primitives.

This module deliberately contains no repository access, model calls, or file
mutation.  It owns the small deterministic part of the v16 requirement and
clarification boundary so the existing execution controller can keep treating
the Project Brain as its planning anchor.
"""

from __future__ import annotations

import copy
import json
import math
import re


USER_STATED = "USER_STATED"
USER_CONFIRMED = "USER_CONFIRMED"
DERIVED = "DERIVED"
VERIFIED = "VERIFIED"

MAX_SOURCE_REQUIREMENTS = 64
MAX_SOURCE_SEGMENTS = 32
MAX_SOURCE_SEGMENT_CHARS = 2200
MAX_SOURCE_REQUIREMENT_CHARS = 1200
MAX_SOURCE_VARIANTS = 4
MAX_CLARIFICATION_QUESTIONS = 3
MAX_CLARIFICATION_OPTIONS = 3


class FrozenList(list):
    """A JSON-compatible list that cannot be mutated in place."""

    def _immutable(self, *_args, **_kwargs):
        raise TypeError("source requirement ledger is immutable")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = _immutable

    def __iadd__(self, _other):
        self._immutable()

    def __imul__(self, _other):
        self._immutable()

    def __deepcopy__(self, memo):
        result = [copy.deepcopy(item, memo) for item in self]
        memo[id(self)] = result
        return result


class FrozenDict(dict):
    """A JSON-compatible mapping that cannot be mutated in place."""

    def _immutable(self, *_args, **_kwargs):
        raise TypeError("source requirement ledger is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable

    def __ior__(self, _other):
        self._immutable()

    def __deepcopy__(self, memo):
        result = {copy.deepcopy(key, memo): copy.deepcopy(value, memo) for key, value in self.items()}
        memo[id(self)] = result
        return result


def freeze(value):
    """Recursively freeze JSON-shaped data while retaining JSON encoding."""
    if isinstance(value, FrozenDict) or isinstance(value, FrozenList):
        return value
    if isinstance(value, dict):
        result = FrozenDict()
        dict.__init__(result, ((key, freeze(item)) for key, item in value.items()))
        return result
    if isinstance(value, (list, tuple)):
        result = FrozenList()
        list.__init__(result, [freeze(item) for item in value])
        return result
    return value


def thaw(value):
    """Return an ordinary mutable deep copy of frozen ledger data."""
    if isinstance(value, dict):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(item) for item in value]
    return copy.deepcopy(value)


def compact_text(value, limit=240):
    text = " ".join(str(value or "").split())
    limit = max(1, int(limit))
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def normalize_requirement_text(value):
    """Normalize only formatting; do not perform broad semantic merging."""
    return compact_text(value, MAX_SOURCE_REQUIREMENT_CHARS)


def _requirement_key(value):
    text = normalize_requirement_text(value).casefold()
    text = re.sub(r"\bw\s*/\s*a\s*/\s*s\s*/\s*d\b", "wasd", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _has_wasd(text):
    value = str(text or "").casefold()
    return bool(re.search(r"\bwasd\b", value) or re.search(r"\bw\s*/\s*a\s*/\s*s\s*/\s*d\b", value))


def _has_negation(text):
    return bool(re.search(r"\b(?:not|never|without|disable|disallow|exclude|remove|no)\b", str(text or "").casefold()))


def _can_merge(a, b):
    first, second = _requirement_key(a), _requirement_key(b)
    if not first or not second:
        return False
    if first == second:
        return True
    # This is intentionally the one small structural equivalence needed by
    # common prompts.  Opposite polarity is never merged.
    if _has_wasd(a) and _has_wasd(b) and _has_negation(a) == _has_negation(b):
        return True
    return False


def _category_for(text):
    value = str(text or "").casefold()
    if any(re.search(rf"\b{re.escape(word)}\b", value) for word in
           ("must not", "do not", "don't", "only", "constraint", "compatible")):
        return "constraint"
    if any(re.search(rf"\b{re.escape(word)}\b", value) for word in
           ("acceptance", "success", "verify", "test", "when done", "pass")):
        return "acceptance"
    if any(re.search(rf"\b{re.escape(word)}\b", value) for word in
           ("persist", "save", "storage", "reload", "restart")):
        return "persistence"
    if any(re.search(rf"\b{re.escape(word)}\b", value) for word in
           ("ui", "button", "keyboard", "touch", "display", "render", "screen")):
        return "interaction"
    if any(re.search(rf"\b{re.escape(word)}\b", value) for word in
           ("architecture", "api", "interface", "endpoint", "migration")):
        return "architecture"
    return "functional"


def bounded_source_segments(raw_prompt, max_segments=MAX_SOURCE_SEGMENTS,
                            segment_chars=MAX_SOURCE_SEGMENT_CHARS):
    """Split a request deterministically without asking a model to remember it all."""
    text = str(raw_prompt or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    max_segments = min(MAX_SOURCE_SEGMENTS, max(1, int(max_segments)))
    segment_chars = max(256, int(segment_chars))
    if not text:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    pieces = []
    for paragraph in paragraphs or [text]:
        if len(paragraph) <= segment_chars:
            pieces.append(paragraph)
            continue
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        if not lines:
            lines = [paragraph]
        current = ""
        for line in lines:
            if len(line) > segment_chars:
                if current:
                    pieces.append(current)
                    current = ""
                for offset in range(0, len(line), segment_chars):
                    pieces.append(line[offset:offset + segment_chars])
                continue
            candidate = f"{current}\n{line}".strip() if current else line
            if current and len(candidate) > segment_chars:
                pieces.append(current)
                current = line
            else:
                current = candidate
        if current:
            pieces.append(current)

    # The segment cap is a safety boundary, not a reason to silently drop the
    # tail.  Join the bounded remainder into the final segment and label it as
    # truncated if even that compact representation cannot fit.
    if len(pieces) > max_segments:
        pieces = pieces[:max_segments - 1] + ["\n".join(pieces[max_segments - 1:])]
        if len(pieces[-1]) > segment_chars:
            pieces[-1] = pieces[-1][: max(0, segment_chars - 3)] + "..."
    return [{"segment": index, "text": piece} for index, piece in enumerate(pieces, 1)]


_BULLET_RE = re.compile(r"^(?:[-*•]|\d+[.)]|[a-zA-Z][.)])\s+(.+)$")
_EXPLICIT_MARKER_RE = re.compile(
    r"\b(?:must|should|shall|need(?:s)? to|support(?:s)?|persist(?:s)?|preserve(?:s)?|keep(?:s)?|"
    r"allow(?:s)?|include(?:s)?|provide(?:s)?|handle(?:s)?|ensure(?:s)?|implement|add|create|build|"
    r"replace|remove|reset|restart|acceptance|success criteria)\b",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^(?:[A-Z][A-Z0-9 _/-]{2,}|(?:requirements?|constraints?|acceptance criteria|notes?))\s*:?$")


def _sentences(text):
    return [part.strip(" \t\n-*") for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def deterministic_requirement_candidates(segment_text, source_segment):
    """Extract obvious explicit statements without pretending to understand everything."""
    lines = [line.strip() for line in str(segment_text or "").splitlines() if line.strip()]
    has_bullets = any(_BULLET_RE.match(line) for line in lines)
    candidates = []
    active_bullet = None
    for line in lines:
        match = _BULLET_RE.match(line)
        if match:
            active_bullet = match.group(1).strip()
            candidates.append({"text": active_bullet, "category": _category_for(active_bullet),
                               "source_segment": source_segment})
            continue
        if active_bullet and not _HEADING_RE.match(line) and not _EXPLICIT_MARKER_RE.search(line):
            # A short continuation line belongs to the preceding bullet.
            candidates[-1]["text"] = normalize_requirement_text(f"{candidates[-1]['text']} {line}")
            continue
        active_bullet = None
        if _HEADING_RE.match(line):
            continue
        if has_bullets and not re.search(
                r"\b(?:must|should|shall|need(?:s)? to|must not|do not|don't|preserve|persist|"
                r"keep|allow|include|ensure|acceptance|success criteria)\b", line, re.IGNORECASE):
            # The introductory project sentence is the root goal, not an
            # additional bullet requirement when a requirements list follows.
            continue
        for sentence in _sentences(line):
            if len(sentence) >= 3 and _EXPLICIT_MARKER_RE.search(sentence):
                candidates.append({"text": sentence, "category": _category_for(sentence),
                                   "source_segment": source_segment})

    if not candidates:
        # Retaining a vague request as one source statement prevents the
        # source contract from becoming empty.  It does not force questions.
        fallback = compact_text(segment_text, MAX_SOURCE_REQUIREMENT_CHARS)
        if fallback:
            candidates.append({"text": fallback, "category": _category_for(fallback),
                               "source_segment": source_segment})

    unique = []
    for candidate in candidates:
        text = normalize_requirement_text(candidate.get("text", ""))
        if not text:
            continue
        candidate = dict(candidate)
        candidate["text"] = text
        if not any(_can_merge(text, item["text"]) for item in unique):
            unique.append(candidate)
    return unique[:MAX_SOURCE_REQUIREMENTS]


def _next_numeric_id(records, prefix):
    numbers = []
    for item in records:
        match = re.match(rf"^{re.escape(prefix)}-(\d+)$", str(item.get("requirement_id") or item.get("decision_id") or ""))
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _merge_record(existing, candidate):
    record = thaw(existing)
    text = normalize_requirement_text(candidate.get("text", ""))
    variants = list(record.get("source_variants", []))
    if text and text not in variants and len(variants) < MAX_SOURCE_VARIANTS:
        variants.append(text)
    segments = list(record.get("source_segments", []))
    segment = candidate.get("source_segment")
    if segment is not None and segment not in segments:
        segments.append(segment)
    # Provenance locations are cheap and bounded by the segment budget; keep
    # every merged location even when only a few wording variants are kept.
    record["source_segments"] = segments[:MAX_SOURCE_SEGMENTS]
    record["source_variants"] = variants[:MAX_SOURCE_VARIANTS]
    return record


def build_source_requirement_ledger(candidates, existing_ledger=None, max_requirements=MAX_SOURCE_REQUIREMENTS):
    """Create a frozen, stable-ID ledger from extracted candidate records."""
    prior = thaw(existing_ledger) if existing_ledger else {}
    records = [thaw(item) for item in prior.get("requirements", []) if isinstance(item, dict)]
    confirmed = [thaw(item) for item in prior.get("confirmed_requirements", []) if isinstance(item, dict)]
    max_requirements = min(MAX_SOURCE_REQUIREMENTS, max(1, int(max_requirements)))
    next_number = _next_numeric_id(records + confirmed, "REQ")
    used_ids = {str(item.get("requirement_id")) for item in records + confirmed}
    for candidate in list(candidates or []):
        if isinstance(candidate, str):
            candidate = {"text": candidate}
        if not isinstance(candidate, dict):
            continue
        text = normalize_requirement_text(candidate.get("text", ""))
        if not text:
            continue
        match = next((index for index, item in enumerate(records) if _can_merge(item.get("text"), text)), None)
        if match is not None:
            records[match] = _merge_record(records[match], {**candidate, "text": text})
            continue
        if len(records) >= max_requirements:
            break
        requested_id = str(candidate.get("requirement_id", ""))
        if not re.match(r"^REQ-\d+$", requested_id) or requested_id in used_ids:
            requested_id = f"REQ-{next_number:03d}"
        record = {
            "requirement_id": requested_id,
            "text": text,
            "category": str(candidate.get("category") or _category_for(text))[:60],
            "provenance": str(candidate.get("provenance") or USER_STATED),
            "source_segment": candidate.get("source_segment"),
            "source_segments": [candidate.get("source_segment")] if candidate.get("source_segment") is not None else [],
            "source_variants": [text],
            "status": str(candidate.get("status") or "active"),
        }
        records.append(record)
        used_ids.add(requested_id)
        requested_number = int(requested_id.split("-", 1)[1])
        next_number = max(next_number, requested_number + 1)
    ledger = {
        "version": 1,
        "immutable": True,
        "requirements": records[:max_requirements],
        "confirmed_requirements": confirmed[:MAX_SOURCE_REQUIREMENTS],
        "limits": {
            "max_requirements": max_requirements,
            "max_segment_chars": MAX_SOURCE_SEGMENT_CHARS,
        },
    }
    return freeze(ledger)


def ledger_requirements(ledger, include_confirmed=False):
    if not isinstance(ledger, dict):
        return []
    records = [thaw(item) for item in ledger.get("requirements", []) if isinstance(item, dict)]
    if include_confirmed:
        records.extend(thaw(item) for item in ledger.get("confirmed_requirements", []) if isinstance(item, dict))
    return records


def append_confirmed_requirement(ledger, text, question_id=None, category=None):
    """Return a new ledger; the original frozen ledger is never modified."""
    result = thaw(ledger) if ledger else build_source_requirement_ledger([])
    records = list(result.get("confirmed_requirements", []))
    decision = {
        "requirement_id": f"REQ-{_next_numeric_id(ledger_requirements(result, True), 'REQ'):03d}",
        "text": normalize_requirement_text(text),
        "category": category or _category_for(text),
        "provenance": USER_CONFIRMED,
        "source_segment": None,
        "source_segments": [],
        "question_id": question_id,
        "status": "active",
    }
    if decision["text"]:
        records.append(decision)
    result["confirmed_requirements"] = records[:MAX_SOURCE_REQUIREMENTS]
    return freeze(result)


def source_contract_from_ledger(raw_goal, ledger, confirmed=None, derived=None, questions=None, answers=None,
                               interaction_style=None):
    stated = ledger_requirements(ledger)
    return {
        "root_goal": compact_text(next((line.strip() for line in str(raw_goal or "").splitlines() if line.strip()), raw_goal), 1200),
        "source_requirement_ledger": ledger,
        "user_stated_requirements": stated,
        "user_confirmed_requirements": [thaw(item) for item in (confirmed or [])],
        "derived_assumptions": [thaw(item) for item in (derived or [])],
        "clarification_questions": [thaw(item) for item in (questions or [])],
        "clarification_answers": [thaw(item) for item in (answers or [])],
        "interaction_style": interaction_style or "LOW_FRICTION",
    }


def _overlap_tokens(first, second):
    stop = {"the", "and", "for", "with", "from", "that", "this", "should", "must", "user", "allow", "support"}
    a = {token for token in re.findall(r"[a-z0-9]{3,}", str(first).casefold()) if token not in stop}
    b = {token for token in re.findall(r"[a-z0-9]{3,}", str(second).casefold()) if token not in stop}
    return a, b


def detect_explicit_conflicts(ledger):
    """Find only visible source conflicts; no repository or architecture inspection is used."""
    records = ledger_requirements(ledger)
    conflicts = []
    for left_index, left in enumerate(records):
        left_text = str(left.get("text", ""))
        left_lower = left_text.casefold()
        for right in records[left_index + 1:]:
            right_text = str(right.get("text", ""))
            right_lower = right_text.casefold()
            first_tokens, second_tokens = _overlap_tokens(left_text, right_text)
            shared_subject = bool(first_tokens & second_tokens)
            conflict_type = None
            if shared_subject and (_has_negation(left_text) != _has_negation(right_text)):
                conflict_type = "opposite_polarity"
            if ((any(phrase in left_lower for phrase in
                     ("reset all", "reset everything", "resets all", "resets everything", "restart", "restarts", "reset the"))) and
                    any(word in right_lower for word in ("persist", "keep", "survive"))):
                conflict_type = "reset_vs_persistence"
            if ((any(phrase in right_lower for phrase in
                     ("reset all", "reset everything", "resets all", "resets everything", "restart", "restarts", "reset the"))) and
                    any(word in left_lower for word in ("persist", "keep", "survive"))):
                conflict_type = "reset_vs_persistence"
            verb_pairs = (
                (("preserve", "keep", "retain"), ("remove", "delete", "discard")),
                (("include", "support", "allow", "enable"), ("exclude", "disable", "disallow")),
                (("online", "cloud"), ("offline", "local only")),
                (("replace", "remove"), ("preserve", "keep", "maintain")),
            )
            if shared_subject:
                for positive, negative in verb_pairs:
                    if (any(word in left_lower for word in positive) and any(word in right_lower for word in negative)) or \
                            (any(word in right_lower for word in positive) and any(word in left_lower for word in negative)):
                        conflict_type = conflict_type or "opposing_behavior"
            if conflict_type:
                conflicts.append({
                    "conflict_id": f"CONFLICT-{len(conflicts) + 1:03d}",
                    "requirement_ids": [left.get("requirement_id"), right.get("requirement_id")],
                    "type": conflict_type,
                    "summary": "Two explicit source requirements may require different behavior.",
                })
    return conflicts[:MAX_CLARIFICATION_QUESTIONS]


def classify_interaction_style(raw_goal, ledger=None):
    """Classify the request threshold, never the person making the request."""
    value = str(raw_goal or "").casefold()
    precision_markers = (
        "backward compatible", "api compatibility", "preserve existing", "without breaking",
        "migration", "replace", "rotate", "production", "schema", "destructive", "delete",
        "exactly", "must preserve", "acceptance criteria", "compatibility", "security",
    )
    if any(marker in value for marker in precision_markers):
        return "PRECISION_SENSITIVE"
    if ledger and detect_explicit_conflicts(ledger):
        return "PRECISION_SENSITIVE"
    return "LOW_FRICTION"


_TRIVIAL_QUESTION_RE = re.compile(
    r"\b(?:helper|function|variable|class) name|file layout|folder structure|css organization|"
    r"exact numeric|exact number|coefficient|internal (?:algorithm|implementation)|button color|"
    r"class vs function|which file|method name|identifier name|enemy hp|hit points\b",
    re.IGNORECASE,
)
_DECISION_CRITICAL_RE = re.compile(
    r"\b(?:conflict\w*|contradict\w*|incompat\w*|destruct\w*|delete\w*|overwrite\w*|preserv\w*|persist\w*|restart\w*|"
    r"acceptance\w*|success\w*|ambig\w*|material|visible behavior|architecture|migration\w*|compatib\w*|"
    r"relationship|trade.?off|cannot safely infer|must choose)\b",
    re.IGNORECASE,
)


def question_is_eligible(question, ledger=None, interaction_style="LOW_FRICTION", conflicts=None):
    """Apply the bounded eligibility rule after any weak-model suggestion."""
    if not isinstance(question, dict):
        return False
    text = str(question.get("question") or question.get("text") or "").strip()
    if len(text) < 8:
        return False
    if question.get("eligible") is False:
        return False
    evidence = " ".join(str(question.get(key, "")) for key in ("reason", "impact_if_unknown", "category", "question"))
    affected = set(str(item) for item in question.get("affected_requirement_ids", []) if item)
    conflict_ids = {str(item) for conflict in (conflicts or []) for item in conflict.get("requirement_ids", [])}
    conflict_question = bool(affected & conflict_ids) or bool(conflicts and question.get("blocking"))
    if _TRIVIAL_QUESTION_RE.search(text) and not _DECISION_CRITICAL_RE.search(evidence):
        return False
    if interaction_style == "LOW_FRICTION" and not conflict_question and not _DECISION_CRITICAL_RE.search(evidence):
        return False
    return bool(
        conflict_question
        or bool(question.get("blocking")) and _DECISION_CRITICAL_RE.search(evidence)
        or _DECISION_CRITICAL_RE.search(evidence) and str(question.get("impact_if_unknown", "")).strip()
    )


def normalize_question(question, index, ledger=None, interaction_style="LOW_FRICTION", conflicts=None):
    if not question_is_eligible(question, ledger, interaction_style, conflicts):
        return None
    question_text = compact_text(question.get("question") or question.get("text"), 420)
    affected = [str(item) for item in question.get("affected_requirement_ids", []) if item]
    known_ids = {str(item.get("requirement_id")) for item in ledger_requirements(ledger)}
    affected = [item for item in affected if not known_ids or item in known_ids]
    options = []
    for option in question.get("options", []) or []:
        option_text = compact_text(option, 260)
        if option_text.casefold() in {"other", "other..."}:
            continue
        if option_text and option_text.casefold() not in {item.casefold() for item in options}:
            options.append(option_text)
        if len(options) >= MAX_CLARIFICATION_OPTIONS:
            break
    recommended = compact_text(question.get("recommended_option", ""), 260)
    if recommended:
        match = next((item for item in options if item.casefold() == recommended.casefold()), None)
        if match:
            options.remove(match)
            options.insert(0, match)
            recommended = match
        elif len(options) < MAX_CLARIFICATION_OPTIONS:
            options.insert(0, recommended)
        else:
            recommended = ""
    if not options:
        options = ["Use the first safe project-compatible behavior"]
        recommended = options[0] if question.get("recommended_option") else ""
    allow_other = bool(question.get("allow_other", True))
    category = compact_text(question.get("category") or question.get("type") or "decision-critical", 80)
    return {
        "question_id": f"Q-{int(index):03d}",
        "question": question_text,
        "reason": compact_text(question.get("reason") or "A material decision is unresolved.", 260),
        "affected_requirement_ids": affected,
        "impact_if_unknown": compact_text(question.get("impact_if_unknown") or "The implementation or acceptance behavior may differ.", 300),
        "recommended_option": recommended,
        "options": options[:MAX_CLARIFICATION_OPTIONS],
        "allow_other": allow_other,
        "blocking": bool(question.get("blocking", False)),
        "category": category,
    }


def question_priority(question):
    """Lower numbers are more important within the bounded question budget."""
    question = question if isinstance(question, dict) else {}
    evidence = " ".join(str(question.get(key, "")) for key in
                         ("category", "question", "reason", "impact_if_unknown"))
    value = evidence.casefold()
    if "conflict" in value or "contradict" in value or question.get("blocking") and "preserv" in value:
        return 0
    if any(marker in value for marker in ("destruct", "delete", "overwrite", "compatib", "migration")):
        return 1
    if any(marker in value for marker in ("acceptance", "success", "cannot determine", "cannot judge")):
        return 2
    if any(marker in value for marker in ("visible behavior", "architecture", "persistence", "restart")):
        return 3
    return 4


def conflict_questions(ledger, conflicts=None):
    """Produce neutral, source-linked questions for explicit contradictions."""
    questions = []
    records = {str(item.get("requirement_id")): item for item in ledger_requirements(ledger)}
    for conflict in conflicts or detect_explicit_conflicts(ledger):
        ids = [str(item) for item in conflict.get("requirement_ids", [])]
        first = records.get(ids[0], {}).get("text", "the first requirement") if ids else "the first requirement"
        second = records.get(ids[1], {}).get("text", "the second requirement") if len(ids) > 1 else "the second requirement"
        if conflict.get("type") == "reset_vs_persistence":
            options = [
                "Keep persistent values, reset only the current run",
                "Reset all state, including persistent values",
                "Keep all current run state",
            ]
            recommended = options[0]
        else:
            options = [compact_text(first, 240), compact_text(second, 240), "Apply a clarified combination of both"]
            recommended = ""
        question = {
            "question": "Which behavior should take precedence for these conflicting requirements?",
            "reason": "The request contains two explicit requirements with opposing behavior.",
            "affected_requirement_ids": ids,
            "impact_if_unknown": "Planning could implement the wrong visible behavior or persistence rule.",
            "options": options,
            "recommended_option": recommended,
            "allow_other": True,
            "blocking": True,
            "category": "conflict",
        }
        normalized = normalize_question(question, len(questions) + 1, ledger, "PRECISION_SENSITIVE", conflicts)
        if normalized:
            questions.append(normalized)
    return questions[:MAX_CLARIFICATION_QUESTIONS]


def specification_coverage(ledger, specification):
    """Map every extracted requirement to the derived spec, conservatively."""
    spec = specification if isinstance(specification, dict) else {}
    fields = {}
    for field, value in spec.items():
        if str(field).startswith("_"):
            continue
        if isinstance(value, list):
            fields[field] = [str(item) for item in value]
        elif isinstance(value, str):
            fields[field] = [value]
    result = []
    for record in ledger_requirements(ledger):
        text = str(record.get("text", ""))
        key = _requirement_key(text)
        tokens, _ = _overlap_tokens(text, text)
        matched_fields = []
        for field, values in fields.items():
            for value in values:
                value_key = _requirement_key(value)
                if key and (key in value_key or value_key in key):
                    matched_fields.append(field)
                    break
                value_tokens, _ = _overlap_tokens(value, value)
                needed = max(2, math.ceil(len(tokens) * 0.7)) if tokens else 99
                if len(tokens & value_tokens) >= needed:
                    matched_fields.append(field)
                    break
        status = "MAPPED" if matched_fields else "UNMAPPED"
        result.append({
            "requirement_id": record.get("requirement_id"),
            "status": status,
            "matched_fields": list(dict.fromkeys(matched_fields))[:6],
        })
    return result


def retention_summary(ledger, retained_records=None, coverage=None):
    extracted = len(ledger_requirements(ledger))
    retained = len([item for item in (retained_records if retained_records is not None else ledger_requirements(ledger))
                    if isinstance(item, dict) and item.get("status", "active") != "discarded"])
    coverage = list(coverage or [])
    mapped = sum(1 for item in coverage if item.get("status") == "MAPPED")
    unmapped = sum(1 for item in coverage if item.get("status") == "UNMAPPED")
    return {
        "source_requirements_extracted": extracted,
        "source_requirements_retained": retained,
        "source_requirements_mapped": mapped,
        "source_requirements_unmapped": unmapped,
        "retention_numerator": retained,
        "retention_denominator": extracted,
        "source_requirement_retention_rate": round(retained / extracted, 4) if extracted else 1.0,
    }


# Public helpers keep the pure boundary convenient for callers and tests.
def extract_source_requirements(raw_prompt, max_segments=MAX_SOURCE_SEGMENTS):
    candidates = []
    for segment in bounded_source_segments(raw_prompt, max_segments=max_segments):
        candidates.extend(deterministic_requirement_candidates(segment["text"], segment["segment"]))
    return build_source_requirement_ledger(candidates)


compute_source_requirement_coverage = specification_coverage
