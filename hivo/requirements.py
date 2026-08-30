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
MAX_SOURCE_EXPLICIT_ITEMS = 64
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


def _normalize_requirement_text_with_status(value):
    text = " ".join(str(value or "").split())
    limit = max(1, int(MAX_SOURCE_REQUIREMENT_CHARS))
    if len(text) <= limit:
        return text, False
    return text[: max(0, limit - 3)] + "...", True


def normalize_requirement_text(value):
    """Normalize only formatting; do not perform broad semantic merging."""
    return _normalize_requirement_text_with_status(value)[0]


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
           ("must not", "do not", "don't", "never", "only", "constraint", "compatible",
            "avoid", "instead", "rather", "reuse", "preserve", "keep", "retain",
            "duplicate", "ownership")):
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
    r"\b(?:must|should|shall|need(?:s)? to|required\s+to|support(?:s)?|persist(?:s)?|"
    r"preserve(?:s|d|ing)?|keep(?:s|ing)?|retain(?:s|ed|ing)?|reuse(?:s|d|ing)?|"
    r"avoid(?:s|ed|ing)?|extend(?:s|ed|ing)?|maintain(?:s|ed|ing)?|require(?:s|d|ing)?|"
    r"introduce(?:s|d|ing)?|update(?:s|d|ing)?|allow(?:s)?|include(?:s)?|provide(?:s)?|"
    r"handle(?:s)?|ensure(?:s)?|implement(?:s|ed|ing)?|add(?:s|ed|ing)?|create(?:s|d|ing)?|build(?:s|ing)?|"
    r"replace(?:s|d|ing)?|remove(?:s|d|ing)?|reset(?:s|ting)?|restart(?:s|ed|ing)?|"
    r"expose(?:s|d|ing)?|use(?:s|d|ing)?|instead\s+of|rather\s+than|acceptance|success criteria|"
    r"including|feature(?:s)?|option(?:s)?|method(?:s)?|mode(?:s)?|example(?:s)?|valid|available|"
    r"following)\b",
    re.IGNORECASE,
)
_SOURCE_LIST_MARKER_RE = re.compile(
    r"\b(?:must|should|shall|need(?:s)? to|required\s+to|support(?:s)?|persist(?:s)?|"
    r"preserve(?:s|d|ing)?|keep(?:s|ing)?|retain(?:s|ed|ing)?|reuse(?:s|d|ing)?|"
    r"avoid(?:s|ed|ing)?|extend(?:s|ed|ing)?|maintain(?:s|ed|ing)?|require(?:s|d|ing)?|"
    r"introduce(?:s|d|ing)?|update(?:s|d|ing)?|allow(?:s)?|include(?:s)?|ensure(?:s)?|restart|"
    r"expose(?:s|d|ing)?|use(?:s|d|ing)?|instead\s+of|rather\s+than|acceptance|success criteria|including|feature(?:s)?|option(?:s)?|method(?:s)?|mode(?:s)?|"
    r"example(?:s)?|valid|available|following)\b",
    re.IGNORECASE,
)
_EXPLICIT_IMPERATIVE_START_RE = re.compile(
    r"^\s*(?:please\s+|you\s+)?(?:add|allow|avoid|build|change|clean|configure|create|delete|"
    r"disable|document|enable|ensure|extend|expose|fix|handle|include|implement|introduce|keep|"
    r"maintain|migrate|modify|preserve|provide|refactor|remove|rename|replace|reset|restart|"
    r"require|reuse|retain|set|simplify|support|test|update|use|verify)\b",
    re.IGNORECASE,
)
_EXPLICIT_NEGATIVE_START_RE = re.compile(
    r"^\s*(?:please\s+)?(?:(?:do|does|did)\s+not|don['’]t|never)\b",
    re.IGNORECASE,
)
_EXPLICIT_MODAL_RE = re.compile(
    r"\b(?:must|should|shall|need(?:s)?\s+to|required\s+to|do\s+not|don['’]t|never)\b",
    re.IGNORECASE,
)
_OBSERVATIONAL_SENTENCE_RE = re.compile(
    r"^\s*(?:(?:the|this|that|an?|our|your)\s+)?"
    r"(?:(?:current|existing|present)\s+)?"
    r"(?:project|repository|codebase|application|app|system|implementation|workspace|package|module|code)\b"
    r"[^.!?;\n]{0,120}\b(?:currently\s+)?(?:use(?:s)?|support(?:s)?|contain(?:s)?|"
    r"include(?:s)?|have|has|is|are|was|were|run(?:s)?|rely|rel(?:y|ies)|"
    r"preserve(?:s)?|keep(?:s)?|retain(?:s)?|reuse(?:s)?|maintain(?:s)?|extend(?:s)?|"
    r"avoid(?:s)?|introduce(?:s)?|implement(?:s)?)\b",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^(?:[A-Z][A-Z0-9 _/-]{2,}|(?:requirements?|constraints?|acceptance criteria|notes?))\s*:?$")
_LIST_INTRO_RE = re.compile(
    r"(?:\b(?:requirements?|constraints?|methods?|options?|features?|examples?|modes?|"
    r"including|following|available|valid|expose(?:s|d|ing)?|allow(?:s)?|"
    r"provide(?:s)?|include(?:s)?)\b|\b(?:supports?|must\s+expose)\b)"
    r"[^\n:]{0,160}:\s*$",
    re.IGNORECASE,
)
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_IDENTIFIER_TOKEN_RE = re.compile(
    r"(?<![\w$])(?:--[A-Za-z][A-Za-z0-9_-]*|"
    r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)"
    r"(?:\([^()\n]*\))?"
)


def _sentences(text):
    return [part.strip(" \t\n-*") for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _is_explicit_requirement_sentence(sentence):
    """Recognize instructional sentences without promoting repository observations."""
    value = str(sentence or "").strip()
    if len(value) < 3:
        return False
    if _EXPLICIT_IMPERATIVE_START_RE.match(value) or _EXPLICIT_NEGATIVE_START_RE.match(value):
        return True
    if _EXPLICIT_MODAL_RE.search(value):
        return True
    # Declarative statements about a project/repository are context unless
    # the sentence is explicitly instructional (handled above).
    if _OBSERVATIONAL_SENTENCE_RE.match(value):
        return False
    return bool(_EXPLICIT_MARKER_RE.search(value))


def has_explicit_requirement_signal(value):
    """Return whether text contains an instructional source-requirement signal."""
    return any(_is_explicit_requirement_sentence(sentence) for sentence in _sentences(value))


def _looks_like_identifier(value):
    value = str(value or "").strip()
    if not value:
        return False
    if value.startswith("--") or ("(" in value and value.endswith(")")):
        return True
    if "." in value or "_" in value:
        return True
    return any(character.isupper() for character in value[1:])


def _single_identifier_line(value):
    """Recognize one structured identifier without splitting ordinary prose."""
    candidate = str(value or "").strip()
    candidate = re.sub(r"^(?:and|or)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = candidate.rstrip(",;.").strip()
    if not candidate:
        return None
    matches = list(_IDENTIFIER_TOKEN_RE.finditer(candidate))
    if len(matches) != 1 or matches[0].group(0) != candidate:
        return None
    return candidate if _looks_like_identifier(candidate) else None


def _explicit_identifier_items(value):
    """Return bounded, source-spelled identifiers from explicit requirement text."""
    text = str(value or "")
    items = []

    def add(item):
        item = " ".join(str(item or "").split()).strip()
        if item and item not in items:
            items.append(item)

    for match in _CODE_SPAN_RE.finditer(text):
        add(match.group(1))
    for match in _IDENTIFIER_TOKEN_RE.finditer(text):
        item = match.group(0)
        if _looks_like_identifier(item):
            add(item)
    return items[:MAX_SOURCE_EXPLICIT_ITEMS], len(items)


def _prepare_requirement_candidate(candidate):
    """Normalize a candidate while retaining explicit structured identifiers."""
    prepared = dict(candidate or {})
    raw_text = prepared.pop("_raw_text", prepared.get("text", ""))
    text, text_truncated = _normalize_requirement_text_with_status(raw_text)
    extracted_items, extracted_count = _explicit_identifier_items(raw_text)
    supplied_items = []
    for item in prepared.get("explicit_items", []) or []:
        item = " ".join(str(item or "").split()).strip()
        if item and item not in supplied_items:
            supplied_items.append(item)
    all_items = []
    for item in supplied_items + extracted_items:
        if item not in all_items:
            all_items.append(item)
    provided_count = prepared.get("explicit_item_count", 0)
    try:
        provided_count = max(0, int(provided_count))
    except (TypeError, ValueError):
        provided_count = 0
    item_count = max(provided_count, extracted_count, len(all_items))
    bounded_items = all_items[:MAX_SOURCE_EXPLICIT_ITEMS]
    omitted_items = max(0, item_count - len(bounded_items))
    prepared["text"] = text
    if text_truncated or prepared.get("text_truncated"):
        prepared["text_truncated"] = True
    else:
        prepared.pop("text_truncated", None)
    if bounded_items:
        prepared["explicit_items"] = bounded_items
        prepared["explicit_item_count"] = item_count
    else:
        prepared.pop("explicit_items", None)
        prepared.pop("explicit_item_count", None)
    if omitted_items or prepared.get("explicit_items_truncated"):
        prepared["explicit_items_truncated"] = True
    else:
        prepared.pop("explicit_items_truncated", None)
    prepared["_explicit_items_omitted"] = omitted_items
    return prepared


def _append_candidate_text(candidate, text):
    current = candidate.get("_raw_text", candidate.get("text", ""))
    candidate["_raw_text"] = f"{current} {text}".strip()


def deterministic_requirement_candidates(segment_text, source_segment):
    """Extract obvious explicit statements without pretending to understand everything."""
    raw_lines = [line for line in str(segment_text or "").splitlines() if line.strip()]
    lines = [(line.strip(), len(line) - len(line.lstrip())) for line in raw_lines]
    has_bullets = any(_BULLET_RE.match(line) for line, _indent in lines)
    candidates = []
    active_index = None
    active_indent = 0
    active_list_intro = False
    for line, indent in lines:
        match = _BULLET_RE.match(line)
        if match:
            bullet = match.group(1).strip()
            candidates.append({"_raw_text": bullet, "category": _category_for(bullet),
                               "source_segment": source_segment})
            active_index = len(candidates) - 1
            active_indent = indent
            active_list_intro = bool(_LIST_INTRO_RE.search(bullet))
            continue
        if active_index is not None and indent > active_indent:
            _append_candidate_text(candidates[active_index], line)
            continue
        if active_index is not None and active_list_intro and _single_identifier_line(line):
            _append_candidate_text(candidates[active_index], line)
            continue
        if active_index is not None and not _HEADING_RE.match(line) and not _EXPLICIT_MARKER_RE.search(line):
            # A short continuation line belongs to the preceding bullet.
            _append_candidate_text(candidates[active_index], line)
            continue
        active_index = None
        active_list_intro = False
        if _HEADING_RE.match(line):
            continue
        if has_bullets and not _SOURCE_LIST_MARKER_RE.search(line):
            # The introductory project sentence is the root goal, not an
            # additional bullet requirement when a requirements list follows.
            continue
        for sentence in _sentences(line):
            if len(sentence) >= 3 and _is_explicit_requirement_sentence(sentence):
                candidates.append({"_raw_text": sentence, "category": _category_for(sentence),
                                   "source_segment": source_segment})
                if _LIST_INTRO_RE.search(sentence):
                    active_index = len(candidates) - 1
                    active_indent = indent
                    active_list_intro = True

    if not candidates:
        # Retaining a vague request as one source statement prevents the
        # source contract from becoming empty.  It does not force questions.
        fallback = str(segment_text or "")
        if fallback and has_explicit_requirement_signal(fallback):
            candidates.append({"_raw_text": fallback, "category": _category_for(fallback),
                               "source_segment": source_segment})

    unique = []
    for candidate in candidates:
        candidate = _prepare_requirement_candidate(candidate)
        text = candidate.get("text", "")
        if not text:
            continue
        if not any(_can_merge(text, item["text"]) for item in unique):
            candidate.pop("_explicit_items_omitted", None)
            unique.append(candidate)
    # The ledger builder, not this segment-local helper, owns the global
    # requirement bound so it can expose any discarded candidates.
    return unique


def _next_numeric_id(records, prefix):
    numbers = []
    for item in records:
        match = re.match(rf"^{re.escape(prefix)}-(\d+)$", str(item.get("requirement_id") or item.get("decision_id") or ""))
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _merge_record(existing, candidate):
    record = thaw(existing)
    candidate = _prepare_requirement_candidate(candidate)
    text = candidate.get("text", "")
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
    existing_items = list(record.get("explicit_items", []))
    candidate_items = list(candidate.get("explicit_items", []))
    explicit_items = []
    for item in existing_items + candidate_items:
        if item not in explicit_items:
            explicit_items.append(item)
    item_count = max(
        int(record.get("explicit_item_count", 0) or 0),
        int(candidate.get("explicit_item_count", 0) or 0),
        len(explicit_items),
    )
    if explicit_items:
        record["explicit_items"] = explicit_items[:MAX_SOURCE_EXPLICIT_ITEMS]
        record["explicit_item_count"] = item_count
    if record.get("text_truncated") or candidate.get("text_truncated"):
        record["text_truncated"] = True
    if (record.get("explicit_items_truncated") or candidate.get("explicit_items_truncated") or
            item_count > len(record.get("explicit_items", []))):
        record["explicit_items_truncated"] = True
    return record


def build_source_requirement_ledger(candidates, existing_ledger=None, max_requirements=MAX_SOURCE_REQUIREMENTS):
    """Create a frozen, stable-ID ledger from extracted candidate records."""
    prior = thaw(existing_ledger) if existing_ledger else {}
    records = [thaw(item) for item in prior.get("requirements", []) if isinstance(item, dict)]
    confirmed = [thaw(item) for item in prior.get("confirmed_requirements", []) if isinstance(item, dict)]
    max_requirements = min(MAX_SOURCE_REQUIREMENTS, max(1, int(max_requirements)))
    next_number = _next_numeric_id(records + confirmed, "REQ")
    used_ids = {str(item.get("requirement_id")) for item in records + confirmed}
    requirements_truncated = 0
    explicit_items_truncated = 0
    text_truncated = 0
    for candidate in list(candidates or []):
        if isinstance(candidate, str):
            candidate = {"text": candidate}
        if not isinstance(candidate, dict):
            continue
        candidate = _prepare_requirement_candidate(candidate)
        text = candidate.get("text", "")
        if not text:
            continue
        explicit_items_truncated += int(candidate.get("_explicit_items_omitted", 0) or 0)
        text_truncated += int(bool(candidate.get("text_truncated")))
        match = next((index for index, item in enumerate(records) if _can_merge(item.get("text"), text)), None)
        if match is not None:
            records[match] = _merge_record(records[match], candidate)
            continue
        if len(records) >= max_requirements:
            requirements_truncated += 1
            continue
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
        for field in ("explicit_items", "explicit_item_count", "explicit_items_truncated", "text_truncated"):
            if field in candidate:
                record[field] = candidate[field]
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
            "max_explicit_items": MAX_SOURCE_EXPLICIT_ITEMS,
        },
    }
    overflow = {
        "requirements_truncated": requirements_truncated,
        "explicit_items_truncated": explicit_items_truncated,
        "text_truncated": text_truncated,
    }
    if any(overflow.values()):
        ledger["overflow"] = overflow
    return freeze(ledger)


def ledger_requirements(ledger, include_confirmed=False):
    if not isinstance(ledger, dict):
        return []
    records = [thaw(item) for item in ledger.get("requirements", []) if isinstance(item, dict)]
    if include_confirmed:
        records.extend(thaw(item) for item in ledger.get("confirmed_requirements", []) if isinstance(item, dict))
    return records


def append_confirmed_requirement(ledger, text, question_id=None, category=None,
                                 affected_requirement_ids=None, repository_evidence_ids=None,
                                 phase=None):
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
        "affected_requirement_ids": [
            str(item) for item in (affected_requirement_ids or []) if item
        ],
        "repository_evidence_ids": [
            str(item) for item in (repository_evidence_ids or []) if item
        ][:8],
        "phase": phase or "REQUEST_CLARIFICATION",
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


_CONFLICT_HEADING_RE = re.compile(
    r"^(?:requirements?|constraints?|acceptance criteria|notes?|"
    r"multiple enemy types must behave differently|example upgrades?)\s*:?[ \t]*$",
    re.IGNORECASE,
)
_CONFLICT_POSITIVE_RE = re.compile(
    r"\b(?:preserve|preserves|preserving|keep|keeps|keeping|retain|retains|retaining|"
    r"persist|persists|persistent|survive|survives|surviving|remain|remains|remaining|"
    r"unchanged|include|includes|including|support|supports|allow|allows|enable|enables|"
    r"maintain|maintains|maintaining|use|uses|using|required|requires|have|has)\b",
    re.IGNORECASE,
)
_CONFLICT_NEGATIVE_RE = re.compile(
    r"\b(?:must\s+not|do\s+not|does\s+not|did\s+not|don['’]t|not|never|without|"
    r"disable|disables|disabling|disallow|disallows|exclude|excludes|excluding|"
    r"remove|removes|removing|delete|deletes|deleting|discard|discards|discarding|"
    r"replace|replaces|replacing|no)\b",
    re.IGNORECASE,
)
_CONFLICT_TARGET_STOP = frozenset({
    "the", "and", "or", "for", "with", "from", "that", "this", "these", "those",
    "should", "must", "shall", "need", "needs", "have", "has", "be", "is", "are",
    "was", "were", "been", "being", "to", "of", "as", "at", "by", "on", "in",
    "into", "across", "after", "before", "during", "through", "all", "every", "each",
    "any", "only", "just", "fully", "completely", "entirely", "current", "same",
    "use", "uses", "using", "preserve", "preserves", "preserving", "keep", "keeps",
    "keeping", "retain", "retains", "retaining", "persist", "persists", "persistent",
    "survive", "survives", "surviving", "remain", "remains", "remaining", "unchanged",
    "include", "includes", "including", "support", "supports", "allow", "allows",
    "enable", "enables", "maintain", "maintains", "maintaining", "require", "requires",
    "required", "remove", "removes", "removing", "delete", "deletes", "deleting", "discard",
    "discards", "discarding", "erase", "erases", "erasing", "clear", "clears", "clearing",
    "reset", "resets", "resetting", "replace", "replaces", "replacing", "disable", "disables",
    "disabling", "disallow", "disallows", "exclude", "excludes", "excluding", "without",
    "never", "not", "no", "static", "genuinely", "polished", "final", "result", "behavior",
    "implementation", "application", "browser", "project", "requirement", "requirements", "controls", "movement",
})
_CONFLICT_CLAUSE_BREAK_RE = re.compile(
    r"[.!?;,\n]|\b(?:but|while|unless|instead|rather\s+than)\b",
    re.IGNORECASE,
)
_RESET_SCOPE_RE = re.compile(
    r"\b(?:erase|erases|erasing|clear|clears|clearing|reset|resets|resetting|"
    r"delete|deletes|deleting|remove|removes|removing)\b"
    r"[^.!?;\n]{0,100}\b(?:all|every|everything|persisted|persistent|saved|stored|data)\b",
    re.IGNORECASE,
)
_RESET_FULL_SCOPE_RE = re.compile(
    r"(?:\b(?:fully|completely|entirely)\b[^.!?;\n]{0,60}\b(?:erase|erases|erasing|"
    r"clear|clears|clearing|reset|resets|resetting|delete|deletes|deleting|remove|removes|removing)\b|"
    r"\b(?:erase|erases|erasing|clear|clears|clearing|reset|resets|resetting|delete|deletes|deleting|"
    r"remove|removes|removing)\b[^.!?;\n]{0,60}\b(?:fully|completely|entirely)\b)",
    re.IGNORECASE,
)
_PERSISTENCE_RE = re.compile(
    r"\b(?:persist|persists|persistent|preserve|preserves|preserving|keep|keeps|keeping|"
    r"retain|retains|retaining|survive|survives|surviving)\b",
    re.IGNORECASE,
)
_OFFLINE_RE = re.compile(
    r"\b(?:only\s+offline|entirely\s+offline|fully\s+offline|offline[- ]only|"
    r"local\s+only|without\s+(?:a\s+)?network|no\s+network)\b",
    re.IGNORECASE,
)
_REMOTE_RE = re.compile(
    r"\b(?:live\s+remote|remote\s+(?:service|server|api|source)|fetched\s+live|"
    r"retrieve\w*[^.!?;\n]{0,60}\blive\b|always\s+(?:retrieve|fetch|load|read)|online\s+only)\b",
    re.IGNORECASE,
)
_RESOURCE_RE = re.compile(
    r"\b(?:data|state|response|responses|service|server|api|source|content|record|records|"
    r"information|request|requests|storage|values?)\b",
    re.IGNORECASE,
)


def _is_conflict_heading(text):
    """Ignore heading-like ledger records as conflict evidence only."""
    value = compact_text(text, 240)
    if not value:
        return True
    return bool(_CONFLICT_HEADING_RE.match(value) or value.rstrip().endswith(":"))


def _conflict_target_tokens(text):
    return {
        token for token in re.findall(r"[a-z0-9]{3,}", str(text or "").casefold())
        if token not in _CONFLICT_TARGET_STOP
    }


def _negative_target_tokens(text):
    """Return only the object of each explicit negative/action phrase."""
    value = str(text or "").casefold()
    targets = set()
    for match in _CONFLICT_NEGATIVE_RE.finditer(value):
        clause = _CONFLICT_CLAUSE_BREAK_RE.split(value[match.end():], maxsplit=1)[0]
        targets.update(_conflict_target_tokens(clause))
    return targets


def _positive_target_tokens(text):
    """Return subjects of affirmative requirements, never treating negation as affirmation."""
    value = str(text or "").casefold()
    if _CONFLICT_POSITIVE_RE.search(value) or not _CONFLICT_NEGATIVE_RE.search(value):
        return _conflict_target_tokens(value)
    return set()


def _lifecycle_kinds(text):
    value = str(text or "").casefold()
    kinds = set()
    if re.search(r"\brestart\w*\b", value):
        kinds.add("restart")
    if re.search(r"\breload\w*\b", value):
        kinds.add("reload")
    return kinds


def _conflict_evidence(left, right, left_text, right_text):
    """Return bounded positive contradiction evidence, or None when uncertain."""
    if _is_conflict_heading(left_text) or _is_conflict_heading(right_text):
        return None

    left_positive = _positive_target_tokens(left_text)
    right_positive = _positive_target_tokens(right_text)
    left_negative = _negative_target_tokens(left_text)
    right_negative = _negative_target_tokens(right_text)

    if left_positive & right_negative or right_positive & left_negative:
        left_effect = compact_text(left_text, 260)
        right_effect = compact_text(right_text, 260)
        return {
            "relationship": "CONFLICT",
            "type": "opposite_polarity",
            "incompatibility": "The requirements explicitly prescribe opposite behavior for the same target.",
            "choice_a_effect": left_effect,
            "choice_b_effect": right_effect,
            "can_satisfy_both": False,
        }

    left_global_reset = bool(_RESET_SCOPE_RE.search(left_text))
    right_global_reset = bool(_RESET_SCOPE_RE.search(right_text))
    left_full_reset = bool(_RESET_FULL_SCOPE_RE.search(left_text))
    right_full_reset = bool(_RESET_FULL_SCOPE_RE.search(right_text))
    left_persistence = bool(_PERSISTENCE_RE.search(left_text))
    right_persistence = bool(_PERSISTENCE_RE.search(right_text))
    same_lifecycle = bool(_lifecycle_kinds(left_text) & _lifecycle_kinds(right_text))
    if ((left_global_reset and right_persistence) or
            (right_global_reset and left_persistence) or
            (left_full_reset and right_persistence and same_lifecycle) or
            (right_full_reset and left_persistence and same_lifecycle)):
        if (left_global_reset or left_full_reset) and right_persistence:
            reset_text, persistence_text = left_text, right_text
        else:
            reset_text, persistence_text = right_text, left_text
        return {
            "relationship": "CONFLICT",
            "type": "reset_vs_persistence",
            "incompatibility": "One requirement erases broad restart state while the other explicitly preserves persisted state.",
            "choice_a_effect": compact_text(reset_text, 260),
            "choice_b_effect": compact_text(persistence_text, 260),
            "can_satisfy_both": False,
        }

    if (_OFFLINE_RE.search(left_text) and _REMOTE_RE.search(right_text) or
            _OFFLINE_RE.search(right_text) and _REMOTE_RE.search(left_text)):
        if _RESOURCE_RE.search(left_text) and _RESOURCE_RE.search(right_text):
            return {
                "relationship": "CONFLICT",
                "type": "offline_vs_remote",
                "incompatibility": "The requirements explicitly mandate local-only data and live remote retrieval for required state.",
                "choice_a_effect": compact_text(left_text, 260),
                "choice_b_effect": compact_text(right_text, 260),
                "can_satisfy_both": False,
            }

    return None


def detect_explicit_conflicts(ledger):
    """Find only visible source conflicts with positive incompatibility evidence."""
    records = ledger_requirements(ledger)
    conflicts = []
    for left_index, left in enumerate(records):
        left_text = str(left.get("text", ""))
        for right in records[left_index + 1:]:
            right_text = str(right.get("text", ""))
            evidence = _conflict_evidence(left, right, left_text, right_text)
            if evidence and evidence.get("can_satisfy_both") is False:
                conflicts.append({
                    "conflict_id": f"CONFLICT-{len(conflicts) + 1:03d}",
                    "requirement_ids": [left.get("requirement_id"), right.get("requirement_id")],
                    **evidence,
                    "summary": "Two explicit source requirements require mutually incompatible behavior.",
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
        "phase": compact_text(question.get("phase") or "REQUEST_CLARIFICATION", 80),
        "repository_evidence_ids": [
            str(item) for item in question.get("repository_evidence_ids", []) if item
        ][:8],
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


def _has_complete_conflict_evidence(conflict):
    if not isinstance(conflict, dict) or conflict.get("relationship") != "CONFLICT":
        return False
    if conflict.get("can_satisfy_both") is not False:
        return False
    effects = [compact_text(conflict.get(key), 260) for key in ("choice_a_effect", "choice_b_effect")]
    return bool(str(conflict.get("incompatibility", "")).strip() and
                effects[0] and effects[1] and effects[0] != effects[1])


def conflict_questions(ledger, conflicts=None):
    """Produce questions only when a conflict has a complete decision record."""
    questions = []
    records = {str(item.get("requirement_id")): item for item in ledger_requirements(ledger)}
    for conflict in conflicts or detect_explicit_conflicts(ledger):
        if not _has_complete_conflict_evidence(conflict):
            # A question without two explicit incompatible outcomes is not a
            # decision the user needs to make.  Keep the conservative default.
            continue
        ids = [str(item) for item in conflict.get("requirement_ids", [])]
        first = records.get(ids[0], {}).get("text", "the first requirement") if ids else "the first requirement"
        second = records.get(ids[1], {}).get("text", "the second requirement") if len(ids) > 1 else "the second requirement"
        options = [
            compact_text(conflict.get("choice_a_effect") or first, 260),
            compact_text(conflict.get("choice_b_effect") or second, 260),
        ]
        recommended = options[1] if conflict.get("type") == "reset_vs_persistence" else ""
        question = {
            "question": f"Which behavior should apply: {options[0]} or {options[1]}?",
            "reason": conflict.get("incompatibility"),
            "affected_requirement_ids": ids,
            "impact_if_unknown": "Proceeding without this decision would violate one explicit requirement.",
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
