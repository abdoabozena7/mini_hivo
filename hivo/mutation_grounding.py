"""Bind initial Worker mutations to source text observed in the current file."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


MUTATION_TOOLS = frozenset({"edit_file", "edit_file_range", "write_file"})
READ_TOOLS = frozenset({"read_file", "read_file_range"})
MAX_REFRESH_LINES = 80
MUTATION_TARGET_UNRESOLVED = "MUTATION_TARGET_UNRESOLVED"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_text(data: bytes) -> str:
    # Match Path.read_text's universal-newline behavior used by the tools.
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


@dataclass
class SourceSpan:
    file_hash: str
    first_line: int
    last_line: int
    text: str
    full_file: bool = False
    missing: bool = False


@dataclass
class MutationGrounding:
    workspace: Path
    approved_targets: tuple[str, ...]
    policy: str = "current"
    anchors: dict[str, list[SourceSpan]] = field(default_factory=dict)
    refresh: dict[str, str] = field(default_factory=dict)
    refresh_anchors: dict[str, SourceSpan] = field(default_factory=dict)
    attempts: list[dict] = field(default_factory=list)
    bounded_refreshes: int = 0
    terminal_reason: str | None = None
    refresh_observations: list[dict] = field(default_factory=list)

    def _relative(self, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return path.resolve().relative_to(self.workspace.resolve()).as_posix().casefold()
        except ValueError:
            return None

    def _approved(self, relative: str | None) -> bool:
        return relative in self.approved_targets

    def _observed_hash(self, relative, path):
        if not self._approved(relative) or path is None:
            return None
        try:
            return _hash(path.read_bytes())
        except OSError:
            return None

    def observe_read(self, name: str, args: dict, result: str, path: Path | None):
        if name not in READ_TOOLS:
            return
        relative = self._relative(path)
        if not self._approved(relative) or path is None:
            return
        if not path.exists():
            if "file does not exist" in str(result).casefold():
                self.anchors[relative] = [SourceSpan("MISSING", 0, 0, "", missing=True)]
            return
        if str(result).casefold().startswith("error:"):
            return
        try:
            data = path.read_bytes()
            source = _source_text(data)
        except (OSError, UnicodeError):
            return
        lines = source.splitlines(keepends=True)
        if name == "read_file":
            if str(result) != source:
                return
            span = SourceSpan(_hash(data), 1, len(lines), source, full_file=True)
        else:
            try:
                first = max(1, int(args.get("start_line") or 1))
                requested_end = args.get("end_line")
                last = min(len(lines), int(requested_end or min(len(lines), first + 199)))
            except (TypeError, ValueError):
                return
            if first > last:
                return
            display_lines = source.splitlines()
            expected_result = f"[lines {first}-{last} of {len(display_lines)}]\n" + "\n".join(
                f"{number}: {line}" for number, line in enumerate(
                    display_lines[first - 1:last], start=first)
            )
            if str(result) != expected_result:
                return
            span = SourceSpan(_hash(data), first, last, "".join(lines[first - 1:last]))
        # Experiment 15: a verified small full read observes exactly the same
        # bounded source as a range read. Tool spelling is not evidence identity.
        refresh_read = name == "read_file_range" or (self.policy == "evidence_bound" and name == "read_file")
        if (refresh_read and self.refresh.get(relative) == "required"
                and 0 < span.last_line - span.first_line + 1 <= MAX_REFRESH_LINES):
            self.refresh[relative] = "ready"
            # A refresh authorizes the existing bounded retry; it must not
            # silently unlock full-file writes or multiple replacements.
            self.refresh_anchors[relative] = SourceSpan(span.file_hash, span.first_line, span.last_line, span.text)
            self.bounded_refreshes += 1
            self.refresh_observations.append({"tool":name,"target":relative,"file_hash":span.file_hash,
                "source_lines":[span.first_line,span.last_line],"span_hash":_hash(span.text.encode("utf-8"))})
        self.anchors.setdefault(relative, []).append(span)
        self.anchors[relative] = self.anchors[relative][-8:]

    def _evidence(self, name: str, args: dict, path: Path | None):
        relative = self._relative(path)
        if not self._approved(relative) or path is None:
            return False, "UNAPPROVED_TARGET", None
        try:
            if not path.exists():
                if name == "write_file" and any(
                    span.missing for span in self.anchors.get(relative, [])
                ):
                    return True, "OBSERVED_NEW_FILE", None
                return False, "MUTATION_ANCHOR_REQUIRED", None
            data = path.read_bytes()
            source = _source_text(data)
        except (OSError, UnicodeError):
            return False, "MUTATION_ANCHOR_REQUIRED", None
        current_hash = _hash(data)
        spans = [item for item in self.anchors.get(relative, [])
                 if item.file_hash == current_hash and not item.missing]
        if self.refresh.get(relative) == "ready":
            refreshed = self.refresh_anchors.get(relative)
            spans = [refreshed] if refreshed and refreshed.file_hash == current_hash else []
        if not spans:
            return False, "MUTATION_ANCHOR_REQUIRED", None
        if name == "write_file":
            return (True, "GROUNDED_FULL_FILE", None) if any(
                item.full_file for item in spans) else (False, "MUTATION_ANCHOR_REQUIRED", None)
        if name == "edit_file_range":
            try:
                first, last = int(args["start_line"]), int(args["end_line"])
            except (KeyError, TypeError, ValueError):
                return False, "MUTATION_ANCHOR_REQUIRED", None
            covered = any(item.first_line <= first <= last <= item.last_line
                          for item in spans)
            return (True, "GROUNDED_SOURCE_SPAN", (first, last)) if covered else (
                False, "MUTATION_ANCHOR_REQUIRED", None)
        old = args.get("old")
        if not isinstance(old, str) or not old:
            return False, "REPLACE_NOT_FOUND", None
        count = source.count(old)
        if count == 0:
            return False, "REPLACE_NOT_FOUND", None
        try:
            expected = int(args.get("expected_replacements") or 1)
        except (TypeError, ValueError):
            return False, "REPLACE_COUNT_MISMATCH", None
        if count != expected:
            return False, "REPLACE_COUNT_MISMATCH", None
        if not any((item.full_file if expected > 1 else old in item.text)
                   for item in spans):
            return False, "MUTATION_ANCHOR_REQUIRED", None
        offset = source.index(old)
        first = source.count("\n", 0, offset) + 1
        last = first + old.count("\n")
        return True, "GROUNDED_EXACT_REPLACE", (first, last)

    def before_mutation(self, name: str, args: dict, path: Path | None,
                        *, tool_step: int):
        if name not in MUTATION_TOOLS:
            return None
        relative = self._relative(path)
        grounded, reason, lines = self._evidence(name, args, path)
        attempt = {
            "tool_step": tool_step, "tool": name, "target": relative,
            "grounded": grounded, "grounding_reason": reason,
            "source_lines": list(lines) if lines else None,
            "executed": False, "applied": False, "rejected": False,
            "evidence_reason":reason, "refresh_state_before":self.refresh.get(relative),
            "request":dict(args),
            "request_hash":_hash(json.dumps(args,sort_keys=True,ensure_ascii=False).encode("utf-8")),
            "source_before_hash":self._observed_hash(relative,path),
        }
        self.attempts.append(attempt)
        if self.policy not in {"evidence_grounded", "evidence_bound"} or not self._approved(relative):
            return {"allowed": True, "attempt": attempt}
        state = self.refresh.get(relative)
        if state == "required":
            reason = MUTATION_TARGET_UNRESOLVED
        elif state == "ready" and not grounded:
            reason = MUTATION_TARGET_UNRESOLVED
        elif not grounded:
            self.refresh[relative] = "required"
        else:
            if state == "ready":
                self.refresh[relative] = "used"
            return {"allowed": True, "attempt": attempt}
        attempt["rejected"] = True
        attempt["grounding_reason"] = reason
        if reason == MUTATION_TARGET_UNRESOLVED:
            self.terminal_reason = reason
            message = (
                f"error: {reason}: one bounded source refresh did not establish "
                f"an exact mutation span in {relative}; file was not changed"
            )
        else:
            message = (
                f"error: {reason}: proposed mutation is not anchored to exact current "
                f"source in {relative}; file was not changed. Call read_file_range "
                f"on the same file for at most {MAX_REFRESH_LINES} lines around the "
                "intended location, then retry once with the exact observed text."
            )
        return {"allowed": False, "attempt": attempt, "result": message}

    def after_mutation(self, decision: dict | None, result: str, *, changed_file: bool):
        if decision is None:
            return
        attempt = decision["attempt"]
        if decision["allowed"]:
            attempt["executed"] = True
            attempt["applied"] = bool(changed_file)
            attempt["rejected"] = not changed_file and str(result).casefold().startswith("error:")
            if (self.policy in {"evidence_grounded", "evidence_bound"} and attempt["rejected"]
                    and "expected" in str(result).casefold()
                    and "replacement" in str(result).casefold()):
                relative = attempt["target"]
                if self.refresh.get(relative) == "used":
                    self.terminal_reason = MUTATION_TARGET_UNRESOLVED
                else:
                    self.refresh[relative] = "required"

    def summary(self):
        return {
            "policy": self.policy,
            "mutation_attempts": len(self.attempts),
            "grounded_mutation_attempts": sum(item["grounded"] for item in self.attempts),
            "rejected_mutation_attempts": sum(item["rejected"] for item in self.attempts),
            "applied_mutation_attempts": sum(item["applied"] for item in self.attempts),
            "first_mutation_attempt_step": self.attempts[0]["tool_step"] if self.attempts else None,
            "first_applied_mutation_step": next((item["tool_step"] for item in self.attempts
                                                if item["applied"]), None),
            "bounded_refreshes": self.bounded_refreshes,
            "terminal_reason": self.terminal_reason,
            "attempts": list(self.attempts),
            "refresh_observations":list(self.refresh_observations),
        }
