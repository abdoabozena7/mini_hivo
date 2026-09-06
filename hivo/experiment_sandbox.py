"""Safe ephemeral sandboxes and anchored counterfactual probes for CORE-3."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .project_brain_refs import TypedReference, canonical_hash
from .repository_map import _safe_relative, _safe_root


OBSERVE_ALLOWED = "OBSERVE_ALLOWED"
EPHEMERAL_PROBE_ALLOWED = "EPHEMERAL_PROBE_ALLOWED"
FINAL_MUTATION_AUTHORIZED = "FINAL_MUTATION_AUTHORIZED"
DNT_PROTECTED = "DNT_PROTECTED"

INVALID_INTERVENTION = "INVALID_INTERVENTION"
EXPERIMENTAL_PROBE_BLOCKED_DNT = "EXPERIMENTAL_PROBE_BLOCKED_DNT"
EXPERIMENTAL_PROBE_BLOCKED_SCOPE = "EXPERIMENTAL_PROBE_BLOCKED_SCOPE"
EXPERIMENTAL_PROBE_BLOCKED_PERMISSION = "EXPERIMENTAL_PROBE_BLOCKED_PERMISSION"
SANDBOX_READY = "SANDBOX_READY"
SANDBOX_DESTROYED = "SANDBOX_DESTROYED"

_FORBIDDEN_DIRECTORY_NAMES = frozenset({
    ".git", ".agent_runs", ".agent_evidence", ".hivo", "output",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
})


class SandboxSecurityError(ValueError):
    """Raised when a diagnostic path or sandbox violates the subject boundary."""


def _normalize_path(value: str | Path) -> str:
    return str(value).replace("\\", "/").strip().lstrip("./")


def _is_forbidden_relative(path: str) -> bool:
    parts = tuple(item for item in path.replace("\\", "/").split("/") if item)
    return any(part in _FORBIDDEN_DIRECTORY_NAMES for part in parts)


def _safe_subject_path(root: Path, value: str | Path) -> tuple[str, Path]:
    try:
        relative = _safe_relative(root, value)
    except ValueError as exc:
        raise SandboxSecurityError(str(exc)) from exc
    if _is_forbidden_relative(relative):
        raise SandboxSecurityError("diagnostic path targets a protected project area")
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SandboxSecurityError("diagnostic path escapes the subject root") from exc
    return relative, target


def _authority_paths(authority: Mapping[str, Any] | None, keys: tuple[str, ...]) -> set[str]:
    if not isinstance(authority, Mapping):
        return set()
    result: set[str] = set()
    for key in keys:
        raw = authority.get(key)
        if isinstance(raw, Mapping):
            raw = raw.get("paths", raw.get("files", ()))
        if isinstance(raw, str):
            raw = (raw,)
        for item in raw or ():
            result.add(_normalize_path(item))
    return result


@dataclass(frozen=True)
class ProbePermission:
    path: str
    classification: str
    probe_allowed: bool
    final_mutation_authorized: bool
    dnt_protected: bool
    reason: str

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "classification": self.classification,
            "probe_allowed": self.probe_allowed,
            "final_mutation_authorized": self.final_mutation_authorized,
            "dnt_protected": self.dnt_protected,
            "reason": self.reason,
        }


def classify_probe_permission(
    path: str | Path,
    project_root: str | Path,
    *,
    authority: Mapping[str, Any] | None = None,
    dnt_paths: tuple[str, ...] | list[str] = (),
) -> ProbePermission:
    root = _safe_root(project_root)
    relative, _ = _safe_subject_path(root, path)
    dnt = {_normalize_path(item) for item in dnt_paths}
    dnt.update(_authority_paths(authority, ("do_not_touch", "dnt", "approved_dnt", "approved_do_not_touch")))
    if relative in dnt:
        return ProbePermission(relative, DNT_PROTECTED, False, False, True, "DNT target is never probe-mutable")
    approved = _authority_paths(authority, (
        "approved_mutation_scope", "mutation_scope", "authorized_paths",
        "approved_scope", "mutation_targets", "approved_mutation_targets",
    ))
    if relative in approved:
        return ProbePermission(relative, FINAL_MUTATION_AUTHORIZED, True, True, False, "existing final mutation scope")
    allow = True if not isinstance(authority, Mapping) else bool(authority.get("allow_ephemeral_probes", True))
    if allow:
        return ProbePermission(relative, EPHEMERAL_PROBE_ALLOWED, True, False, False, "diagnostic-only ephemeral probe policy")
    return ProbePermission(relative, OBSERVE_ALLOWED, False, False, False, "authority permits observation but not probe mutation")


@dataclass(frozen=True)
class CounterfactualMutationSpec:
    """An anchored, temporary mutation request; never a canonical patch."""

    target_reference: TypedReference
    expected_current_hash: str = ""
    expected_anchor: str = ""
    expected_anchor_hash: str = ""
    operation: str = "exact_anchored_replacement"
    temporary_replacement: str = ""
    reason: str = ""
    hypothesis_ids: tuple[str, ...] = ()
    rollback_guarantee: str = "sandbox_destroyed_after_receipt"
    permission_classification: str = EPHEMERAL_PROBE_ALLOWED

    def __post_init__(self) -> None:
        try:
            ref = self.target_reference if isinstance(self.target_reference, TypedReference) else TypedReference.from_value(self.target_reference)
        except (TypeError, ValueError) as exc:
            raise ValueError("counterfactual target must be a typed reference") from exc
        if ref.kind not in {"file", "symbol", "test"} or not ref.path:
            raise ValueError("counterfactual target must identify a repository path")
        if not self.expected_current_hash and self.expected_anchor_hash:
            object.__setattr__(self, "expected_current_hash", str(self.expected_anchor_hash))
        if not self.expected_current_hash and not self.expected_anchor:
            raise ValueError("counterfactual mutation must be anchored by a hash or exact anchor")
        object.__setattr__(self, "target_reference", ref)
        object.__setattr__(self, "expected_current_hash", str(self.expected_current_hash).lower())
        object.__setattr__(self, "expected_anchor_hash", str(self.expected_anchor_hash).lower())
        object.__setattr__(self, "expected_anchor", str(self.expected_anchor))
        object.__setattr__(self, "temporary_replacement", str(self.temporary_replacement))
        object.__setattr__(self, "hypothesis_ids", tuple(sorted(set(str(item) for item in self.hypothesis_ids))))

    @property
    def target_path(self) -> str:
        return self.target_reference.path

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "target_reference": self.target_reference.to_dict(),
            "expected_current_hash": self.expected_current_hash,
            "expected_anchor_hash": self.expected_anchor_hash,
            "expected_anchor": self.expected_anchor,
            "operation": self.operation,
            "temporary_replacement": self.temporary_replacement,
            "reason": self.reason,
            "hypothesis_ids": list(self.hypothesis_ids),
            "rollback_guarantee": self.rollback_guarantee,
            "permission_classification": self.permission_classification,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class SyntaxValidation:
    valid: bool
    status: str
    error: str = ""
    parser: str = "deterministic_balanced_delimiter_check"

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "status": self.status, "error": self.error, "parser": self.parser}


@dataclass(frozen=True)
class SandboxMutationResult:
    valid: bool
    status: str
    path: str
    intervention_hash: str = ""
    permission: ProbePermission | None = None
    syntax: SyntaxValidation | None = None
    filesystem_changed: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "status": self.status,
            "path": self.path,
            "intervention_hash": self.intervention_hash,
            "permission": self.permission.to_dict() if self.permission else None,
            "syntax": self.syntax.to_dict() if self.syntax else None,
            "filesystem_changed": self.filesystem_changed,
            "reason": self.reason,
        }


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_delimiters(text: str) -> SyntaxValidation:
    stack: list[str] = []
    pairs = {"}": "{", "]": "[", ")": "("}
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char in "'\"`":
            quote = char
        elif char in "([{":
            stack.append(char)
        elif char in ")]}":
            if not stack or stack[-1] != pairs[char]:
                return SyntaxValidation(False, "SYNTAX_INVALID", f"unexpected delimiter {char}")
            stack.pop()
        index += 1
    if quote:
        return SyntaxValidation(False, "SYNTAX_INVALID", "unterminated string literal")
    if block_comment:
        return SyntaxValidation(False, "SYNTAX_INVALID", "unterminated block comment")
    if stack:
        return SyntaxValidation(False, "SYNTAX_INVALID", "unbalanced delimiters")
    return SyntaxValidation(True, "SYNTAX_PASS")


def validate_source_syntax(path: str | Path, text: str) -> SyntaxValidation:
    suffix = Path(str(path)).suffix.casefold()
    if suffix == ".py":
        try:
            compile(text, str(path), "exec")
        except SyntaxError as exc:
            return SyntaxValidation(False, "SYNTAX_INVALID", f"{exc.msg} at line {exc.lineno}", "python_compile")
        return SyntaxValidation(True, "SYNTAX_PASS", parser="python_compile")
    return _validate_delimiters(text)


def subject_tree_snapshot(root: str | Path) -> dict[str, Any]:
    """Hash canonical subject files while excluding runtime/output domains."""
    canonical_root = _safe_root(root)
    rows: list[dict[str, Any]] = []
    total_bytes = 0
    for current, directories, filenames in os.walk(canonical_root, topdown=True, followlinks=False):
        current_path = Path(current)
        for directory in directories:
            if (current_path / directory).is_symlink():
                raise SandboxSecurityError("symlink directories are not allowed in diagnostic subject materialization")
        directories[:] = sorted(name for name in directories if name not in _FORBIDDEN_DIRECTORY_NAMES)
        for name in sorted(filenames):
            path = current_path / name
            if path.is_symlink():
                raise SandboxSecurityError("symlinks are not allowed in diagnostic subject materialization")
            relative = path.relative_to(canonical_root).as_posix()
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            total_bytes += len(data)
            rows.append({"path": relative, "sha256": digest, "bytes": len(data)})
    rows.sort(key=lambda item: item["path"])
    return {
        "root_kind": "canonical_subject",
        "file_count": len(rows),
        "byte_count": total_bytes,
        "files": rows,
        "tree_digest": canonical_hash(rows),
    }


def canonical_subject_hash(root: str | Path) -> str:
    return str(subject_tree_snapshot(root)["tree_digest"])


class ExperimentalSandbox:
    """Complete-copy sandbox with explicit destruction and no git integration."""

    def __init__(
        self,
        canonical_root: str | Path,
        *,
        session_id: str = "diagnostic",
        authority: Mapping[str, Any] | None = None,
        dnt_paths: tuple[str, ...] | list[str] = (),
        temporary_parent: str | Path | None = None,
    ) -> None:
        self.canonical_root = _safe_root(canonical_root)
        self.session_id = str(session_id)
        self.authority = dict(authority or {})
        self.dnt_paths = tuple(dnt_paths)
        self.temporary_parent = Path(temporary_parent).expanduser().resolve() if temporary_parent else None
        self.sandbox_root: Path | None = None
        self.canonical_before: dict[str, Any] | None = None
        self.sandbox_files_materialized = 0
        self.sandbox_bytes_materialized = 0
        self.destroyed = False

    def __enter__(self) -> "ExperimentalSandbox":
        self.canonical_before = subject_tree_snapshot(self.canonical_root)
        if self.temporary_parent is not None:
            if self.temporary_parent == self.canonical_root or self.canonical_root in self.temporary_parent.parents:
                raise SandboxSecurityError("sandbox temporary parent cannot be inside the canonical subject")
            self.temporary_parent.mkdir(parents=True, exist_ok=True)
        self.sandbox_root = Path(tempfile.mkdtemp(prefix="hivo-core3-", dir=str(self.temporary_parent) if self.temporary_parent else None))
        try:
            for row in self.canonical_before["files"]:
                relative = str(row["path"])
                source = self.canonical_root / relative
                destination = self.sandbox_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                self.sandbox_files_materialized += 1
                self.sandbox_bytes_materialized += int(row["bytes"])
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    @property
    def sandbox_identity(self) -> str:
        return canonical_hash({
            "session_id": self.session_id,
            "canonical_subject": self.canonical_before.get("tree_digest") if self.canonical_before else "",
            "materialized_files": self.sandbox_files_materialized,
        })

    def _sandbox_file(self, path: str | Path) -> tuple[str, Path]:
        if self.sandbox_root is None:
            raise SandboxSecurityError("sandbox is not active")
        relative, _ = _safe_subject_path(self.canonical_root, path)
        target = (self.sandbox_root / relative).resolve()
        try:
            target.relative_to(self.sandbox_root)
        except ValueError as exc:
            raise SandboxSecurityError("sandbox path escapes sandbox root") from exc
        return relative, target

    def apply_mutation(self, spec: CounterfactualMutationSpec) -> SandboxMutationResult:
        try:
            relative, sandbox_path = self._sandbox_file(spec.target_path)
            permission = classify_probe_permission(relative, self.canonical_root, authority=self.authority, dnt_paths=self.dnt_paths)
        except (ValueError, SandboxSecurityError) as exc:
            return SandboxMutationResult(False, EXPERIMENTAL_PROBE_BLOCKED_SCOPE, str(getattr(spec, "target_path", "")), reason=str(exc))
        if permission.classification == DNT_PROTECTED:
            return SandboxMutationResult(False, EXPERIMENTAL_PROBE_BLOCKED_DNT, relative, permission=permission, reason=permission.reason)
        if not permission.probe_allowed:
            return SandboxMutationResult(False, EXPERIMENTAL_PROBE_BLOCKED_PERMISSION, relative, permission=permission, reason=permission.reason)
        canonical_path = self.canonical_root / relative
        if not canonical_path.is_file() or not sandbox_path.is_file():
            return SandboxMutationResult(False, INVALID_INTERVENTION, relative, permission=permission, reason="target file is unavailable")
        canonical_hash_value = _source_hash(canonical_path)
        if spec.expected_current_hash and canonical_hash_value != spec.expected_current_hash:
            return SandboxMutationResult(False, INVALID_INTERVENTION, relative, permission=permission, reason="current target hash does not match anchor")
        text = sandbox_path.read_text(encoding="utf-8", errors="replace")
        if spec.expected_anchor:
            count = text.count(spec.expected_anchor)
            if count != 1:
                return SandboxMutationResult(False, INVALID_INTERVENTION, relative, permission=permission, reason=f"expected exact anchor count 1, found {count}")
            replacement = text.replace(spec.expected_anchor, spec.temporary_replacement, 1)
        else:
            return SandboxMutationResult(False, INVALID_INTERVENTION, relative, permission=permission, reason="exact anchor text is required for this probe")
        if replacement == text:
            return SandboxMutationResult(False, INVALID_INTERVENTION, relative, permission=permission, reason="intervention produced no change")
        sandbox_path.write_text(replacement, encoding="utf-8")
        intervention_hash = canonical_hash({"path": relative, "before": hashlib.sha256(text.encode()).hexdigest(), "after": hashlib.sha256(replacement.encode()).hexdigest()})
        syntax = validate_source_syntax(relative, replacement)
        if not syntax.valid:
            return SandboxMutationResult(True, INVALID_INTERVENTION, relative, intervention_hash, permission, syntax, True, syntax.error)
        return SandboxMutationResult(True, "EXPERIMENTAL_MUTATION_APPLIED", relative, intervention_hash, permission, syntax, True, "temporary sandbox-only mutation")

    def canonical_unchanged(self) -> bool:
        return self.canonical_before is not None and subject_tree_snapshot(self.canonical_root) == self.canonical_before

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self.sandbox_root is not None and self.sandbox_root.exists():
            shutil.rmtree(self.sandbox_root, ignore_errors=True)
        self.destroyed = True
        self.sandbox_root = None


__all__ = [
    "OBSERVE_ALLOWED", "EPHEMERAL_PROBE_ALLOWED", "FINAL_MUTATION_AUTHORIZED", "DNT_PROTECTED",
    "INVALID_INTERVENTION", "EXPERIMENTAL_PROBE_BLOCKED_DNT", "EXPERIMENTAL_PROBE_BLOCKED_SCOPE",
    "EXPERIMENTAL_PROBE_BLOCKED_PERMISSION", "SANDBOX_READY", "SANDBOX_DESTROYED",
    "SandboxSecurityError", "ProbePermission", "classify_probe_permission",
    "CounterfactualMutationSpec", "SyntaxValidation", "SandboxMutationResult",
    "validate_source_syntax", "subject_tree_snapshot", "canonical_subject_hash", "ExperimentalSandbox",
]
