"""Deterministic lexical navigation within approved inspection paths."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


STOPWORDS = frozenset({
    "a", "after", "allow", "an", "and", "are", "as", "at", "be", "by",
    "can", "change", "current", "do", "does", "existing", "for", "from",
    "in", "into", "is", "it", "logic", "make", "modify", "of", "on",
    "or", "over", "post", "preserve", "preserving", "should", "the",
    "this", "to", "use", "while", "with", "without",
})
MAX_FILES = 24
MAX_FILE_BYTES = 400_000
MAX_CANDIDATES = 3
WINDOW_RADIUS = 7


def _terms(text):
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", str(text or ""))
    parts = []
    for token in tokens:
        token = re.sub(r"([a-z])([A-Z])", r"\1 \2", token)
        for part in re.split(r"[_\s]+", token):
            part = part.casefold()
            if (len(part) >= 3 or len(part) == 1) and part not in STOPWORDS:
                parts.append(part)
    return parts


def _query_terms(task_text, contract):
    texts = [str(task_text or ""), str(contract.get("goal") or "")]
    for key in ("requirements", "done_when", "interfaces_to_reuse"):
        for item in contract.get(key, []) or []:
            texts.append(str(item.get("text") if isinstance(item, dict) else item))
    counts = Counter(term for text in texts for term in _terms(text))
    if "key" in counts or "keyboard" in counts:
        # Standard keyboard event identifiers are lexical variants of the
        # requirement's input term, independent of any particular key.
        counts["keydown"] = max(counts["keydown"], 4)
        counts["keyup"] = max(counts["keyup"], 2)
        counts["event.key"] = max(counts["event.key"], 3)
    return {term: min(count, 4) for term, count in counts.items()}


def _present(term, lower):
    return bool(re.search(r"\b" + re.escape(term) + r"\b", lower)) if len(term) == 1 else term in lower


def _section_weights(path, lines):
    if path.suffix.casefold() == ".css":
        return [0.35] * len(lines)
    if path.suffix.casefold() not in {".html", ".htm"}:
        return [1.0] * len(lines)
    section = "markup"
    weights = []
    for line in lines:
        lower = line.casefold()
        if "<style" in lower:
            section = "style"
        elif "<script" in lower:
            section = "script"
        weights.append(1.4 if section == "script" else 0.35 if section == "style" else 0.8)
        if "</style" in lower or "</script" in lower:
            section = "markup"
    return weights


@dataclass
class TargetLocator:
    workspace: Path
    approved_paths: tuple[str, ...]
    query_terms: dict[str, int]
    candidates: list[dict] = field(default_factory=list)
    read_events: list[dict] = field(default_factory=list)

    @classmethod
    def build(cls, workspace, task_text, contract):
        workspace = Path(workspace).resolve()
        approved = tuple(str(item).replace("\\", "/") for item in (
            contract.get("allowed_inspection_paths") or []))
        locator = cls(workspace, approved, _query_terms(task_text, contract))
        locator._rank()
        return locator

    def _rank(self):
        sources = []
        for relative in self.approved_paths[:MAX_FILES]:
            path = (self.workspace / relative).resolve()
            if not path.is_relative_to(self.workspace) or not path.is_file():
                continue
            try:
                data = path.read_bytes()
                if len(data) > MAX_FILE_BYTES:
                    continue
                lines = data.decode("utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            sources.append((relative, path, data, lines, _section_weights(path, lines)))
        if not sources or not self.query_terms:
            return
        total_lines = sum(len(item[3]) for item in sources)
        frequency = Counter()
        for _relative, _path, _data, lines, _weights in sources:
            for line in lines:
                lower = line.casefold()
                frequency.update(term for term in self.query_terms if _present(term, lower))
        scored = []
        for relative, _path, data, lines, section_weights in sources:
            direct = []
            matches = []
            for index, line in enumerate(lines):
                lower = line.casefold()
                found = {term for term in self.query_terms if _present(term, lower)}
                score = sum(
                    self.query_terms[term]
                    * min(5.0, 1.0 + math.log((total_lines + 1) / (frequency[term] + 1)))
                    * (1.35 if re.search(r"\b" + re.escape(term) + r"\b", lower) else 1.0)
                    for term in found
                ) * section_weights[index]
                direct.append(score)
                matches.append(found)
            file_hash = hashlib.sha256(data).hexdigest()
            for index, score in enumerate(direct):
                if score <= 0:
                    continue
                first = max(0, index - WINDOW_RADIUS)
                last = min(len(lines), index + WINDOW_RADIUS + 1)
                window_score = sum(direct[first:last])
                found = sorted(set().union(*matches[first:last]))
                scored.append({
                    "path": relative, "start_line": first + 1, "end_line": last,
                    "score": round(window_score, 3), "matched_terms": found,
                    "file_sha256": file_hash,
                })
        scored.sort(key=lambda item: (-item["score"], item["path"], item["start_line"]))
        for item in scored:
            if any(item["path"] == picked["path"] and not (
                item["end_line"] < picked["start_line"] - 2
                or item["start_line"] > picked["end_line"] + 2
            ) for picked in self.candidates):
                continue
            item["candidate_id"] = f"LOC-{len(self.candidates) + 1:03d}"
            self.candidates.append(item)
            if len(self.candidates) >= MAX_CANDIDATES:
                break

    def candidate(self, candidate_id):
        return next((item for item in self.candidates
                     if item["candidate_id"] == candidate_id), None)

    def packet(self):
        if not self.candidates:
            return "TARGET LOCATOR: no lexical candidate was found in approved inspection paths."
        lines = ["TARGET LOCATOR: choose a candidate ID with read_candidate_span before editing. "
                 "The controller owns its path and line range; do not invent line numbers."]
        for item in self.candidates:
            lines.append(
                f"{item['candidate_id']}: {item['path']}:{item['start_line']}-{item['end_line']} "
                f"matched={','.join(item['matched_terms'][:8])}"
            )
        return "\n".join(lines)

    def summary(self):
        return {
            "approved_paths": list(self.approved_paths),
            "query_terms": sorted(self.query_terms),
            "candidates": list(self.candidates),
            "read_events": list(self.read_events),
        }
