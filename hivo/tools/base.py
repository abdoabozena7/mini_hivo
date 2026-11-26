"""Core primitives, contracts, safety guards, and Hashline helpers for hivo.tools.

This module is strictly framework-free and has zero dependencies on ``mini.py``
or legacy global state.
"""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Literal, Mapping, Sequence
import uuid

EffectType = Literal["read", "write", "exec", "control"]
ModelTier = Literal["slm_safe", "orchestrator_only"]

ERR_TOOL_SCHEMA = "TOOL_SCHEMA_ERROR"
ERR_EDIT_APPLY = "EDIT_APPLY_ERROR"
ERR_PATH_SECURITY = "PATH_SECURITY_ERROR"
ERR_ORACLE_LOCKED = "ORACLE_LOCKED"
ERR_COMMAND_REFUSED = "COMMAND_REFUSED"
ERR_COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
ERR_NOT_FOUND = "NOT_FOUND"
ERR_INVALID_TARGET = "INVALID_TARGET"
ERR_HOOK_BLOCKED = "HOOK_BLOCKED"
ERR_INFRA = "INFRA_ERROR"

DEFAULT_IGNORED_DIRS: frozenset[str] = frozenset({
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".hivo",
    ".agent_backups",
    ".agent_runs",
    ".agent_evidence",
})

_SAFE_ENV_FILES: frozenset[str] = frozenset({
    ".env.example",
    ".env.sample",
    ".env.template",
})
_SECRET_BASENAMES: frozenset[str] = frozenset({
    ".env",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    ".netrc",
    ".npmrc",
    ".pypirc",
})
_SECRET_SUFFIXES: frozenset[str] = frozenset({".pem", ".key", ".p12", ".pfx"})


@dataclass(frozen=True)
class ToolContext:
    """Immutable per-execution context passed by the caller to every tool."""

    workspace_root: Path
    allowed_paths: tuple[str, ...] | None = None
    protected_paths: tuple[str, ...] = ()
    block_secret_files: bool = True
    max_read_lines: int = 250
    max_output_chars: int = 16_000
    max_list_entries: int = 200
    max_search_matches: int = 50
    timeout_sec: int = 30
    scratch_dir: Path | None = None
    allowed_commands: tuple[str, ...] | None = None
    enable_backups: bool = False
    error_verbosity: Literal["detailed", "compact"] = "detailed"
    hooks: Any | None = None
    post_edit_commands: tuple[tuple[str, ...], ...] = ()
    worker_dispatcher: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    plan_store: Any | None = None
    user_prompter: Callable[[str, list[str]], str] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_root", Path(self.workspace_root).resolve())
        if self.allowed_paths is not None:
            object.__setattr__(self, "allowed_paths", tuple(str(p) for p in self.allowed_paths))
        object.__setattr__(self, "protected_paths", tuple(str(p) for p in self.protected_paths))
        if self.scratch_dir is not None:
            object.__setattr__(self, "scratch_dir", Path(self.scratch_dir).resolve())
        if self.allowed_commands is not None:
            object.__setattr__(self, "allowed_commands", tuple(str(c) for c in self.allowed_commands))
        object.__setattr__(
            self,
            "post_edit_commands",
            tuple(tuple(str(part) for part in cmd) for cmd in self.post_edit_commands),
        )


@dataclass(frozen=True)
class ToolSpec:
    """Role-agnostic specification for one standalone tool unit."""

    name: str
    description: str
    effect: EffectType
    model_tier: ModelTier
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], ToolContext], dict[str, Any]]


def ok_result(
    data: dict[str, Any],
    *,
    truncated: bool = False,
    hint: str | None = None,
) -> dict[str, Any]:
    """Build a uniform successful tool return envelope."""
    return {
        "ok": True,
        "data": data,
        "error": None,
        "error_code": None,
        "hint": hint,
        "truncated": bool(truncated),
    }


def err_result(
    error: str,
    *,
    hint: str,
    error_code: str = ERR_INFRA,
    data: dict[str, Any] | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    """Build a uniform failed tool return envelope with a mandatory hint and error_code."""
    return {
        "ok": False,
        "data": data if data is not None else {},
        "error": str(error),
        "error_code": str(error_code),
        "hint": str(hint),
        "truncated": bool(truncated),
    }


def serialize_envelope(envelope: Mapping[str, Any]) -> str:
    """Deterministically serialize a tool envelope to JSON."""
    return json.dumps(dict(envelope), ensure_ascii=False, sort_keys=True)


def format_tool_observation(
    tool_name: str,
    envelope: Mapping[str, Any],
    *,
    error_verbosity: str = "detailed",
    wrap_untrusted: bool = True,
) -> str:
    """Format a tool envelope for model consumption with optional compact errors and untrusted framing."""
    view: dict[str, Any] = dict(envelope)
    if error_verbosity == "compact" and not view.get("ok"):
        raw_data = view.get("data")
        compact_data: dict[str, Any] = {}
        if isinstance(raw_data, Mapping):
            for key in ("path", "exit_code", "timed_out", "log_path"):
                if key in raw_data:
                    compact_data[key] = raw_data[key]
        view["data"] = compact_data
        hint_val = view.get("hint")
        if isinstance(hint_val, str) and len(hint_val) > 180:
            view["hint"] = hint_val[:177] + "..."

    serialized = serialize_envelope(view)
    if not wrap_untrusted:
        return serialized
    safe_payload = serialized.replace("</tool_observation>", "<\\/tool_observation>")
    safe_tool = str(tool_name).replace('"', "'")
    return f'<tool_observation tool="{safe_tool}" untrusted_data="true">\n{safe_payload}\n</tool_observation>'


def effective_scratch_dir(ctx: ToolContext) -> Path:
    """Return the external scratch directory used for overflow logs, backups, and checkpoints."""
    if ctx.scratch_dir is not None:
        return ctx.scratch_dir
    ws_hash = hashlib.blake2b(str(ctx.workspace_root).encode("utf-8"), digest_size=6).hexdigest()
    return Path(tempfile.gettempdir()).resolve() / "hivo_tool_scratch" / ws_hash


def is_secret_path(rel_posix: str) -> bool:
    """Return True if ``rel_posix`` points to a secret/credential file blocked by workspace policy."""
    cleaned = rel_posix.replace("\\", "/").strip("/")
    if not cleaned or cleaned == ".":
        return False
    parts = [p.casefold() for p in cleaned.split("/")]
    basename = parts[-1]
    if basename in _SAFE_ENV_FILES:
        return False
    if basename in _SECRET_BASENAMES or basename.startswith(".env."):
        return True
    if any(part in {".ssh", ".aws"} for part in parts[:-1]):
        return True
    suffix = Path(basename).suffix
    if suffix in _SECRET_SUFFIXES:
        return True
    if "credentials" in basename and suffix == ".json":
        return True
    return False


def is_protected_path(rel_posix: str, ctx: ToolContext) -> bool:
    """Return True if ``rel_posix`` matches any completion-oracle lock pattern in ``ctx.protected_paths``."""
    if not ctx.protected_paths:
        return False
    cleaned = rel_posix.replace("\\", "/").lstrip("./")
    basename = Path(cleaned).name
    for raw_pat in ctx.protected_paths:
        pat = raw_pat.strip().replace("\\", "/").lstrip("./")
        if not pat:
            continue
        dir_prefix = pat[:-3] if pat.endswith("/**") else pat.rstrip("/")
        if cleaned == dir_prefix or cleaned.startswith(dir_prefix + "/"):
            return True
        if "/" not in pat and "*" not in pat and "?" not in pat and basename == pat:
            return True
        if fnmatch.fnmatch(cleaned, pat) or ("/" not in pat and fnmatch.fnmatch(basename, pat)):
            return True
    return False


def _schema_summary(parameters: dict[str, Any]) -> str:
    props = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
    required = set(parameters.get("required", []) if isinstance(parameters, dict) else [])
    parts: list[str] = []
    for key, spec in props.items():
        ptype = spec.get("type", "any")
        opt = "" if key in required else " (optional)"
        parts.append(f"{key}: {ptype}{opt}")
    return ", ".join(parts) or "no parameters"


def _validate_value(value: Any, schema: dict[str, Any], label: str) -> tuple[Any, str | None]:
    expected_type = schema.get("type")

    if expected_type == "string":
        if not isinstance(value, str):
            return None, f"'{label}' must be a string"
        enum = schema.get("enum")
        if enum is not None and value not in enum:
            return None, f"'{label}' must be one of {enum}, got {value!r}"
        return value, None

    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return None, f"'{label}' must be an integer"
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            return None, f"'{label}' must be >= {minimum}, got {value}"
        if maximum is not None and value > maximum:
            return None, f"'{label}' must be <= {maximum}, got {value}"
        enum = schema.get("enum")
        if enum is not None and value not in enum:
            return None, f"'{label}' must be one of {enum}, got {value!r}"
        return value, None

    if expected_type == "boolean":
        if not isinstance(value, bool):
            return None, f"'{label}' must be a boolean"
        return value, None

    if expected_type == "array":
        if not isinstance(value, list):
            return None, f"'{label}' must be an array"
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None and len(value) < min_items:
            return None, f"'{label}' must contain at least {min_items} item(s)"
        if max_items is not None and len(value) > max_items:
            return None, f"'{label}' must contain at most {max_items} item(s)"
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            validated_items: list[Any] = []
            for idx, item in enumerate(value):
                parsed, err = _validate_value(item, item_schema, f"{label}[{idx}]")
                if err:
                    return None, err
                validated_items.append(parsed)
            return validated_items, None
        return list(value), None

    if expected_type == "object":
        if not isinstance(value, dict):
            return None, f"'{label}' must be a JSON object"
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unexpected = sorted(str(k) for k in value if k not in props)
            if unexpected:
                return None, f"unexpected parameter(s) in '{label}': {', '.join(unexpected)}"
        required = schema.get("required", [])
        missing = [k for k in required if k not in value or value.get(k) is None]
        if missing:
            return None, f"missing required parameter(s) in '{label}': {', '.join(missing)}"

        out: dict[str, Any] = {}
        for key, prop_schema in props.items():
            if key in value and value[key] is not None:
                parsed, err = _validate_value(value[key], prop_schema, f"{label}.{key}")
                if err:
                    return None, err
                out[key] = parsed
            elif key in value and value[key] is None and key not in required:
                if "default" in prop_schema:
                    out[key] = copy.deepcopy(prop_schema["default"])
            elif "default" in prop_schema:
                out[key] = copy.deepcopy(prop_schema["default"])

        if schema.get("additionalProperties") is not False:
            for key, val in value.items():
                if key not in props:
                    out[key] = val
        return out, None

    return value, None


def validate_and_prepare_args(
    spec: ToolSpec,
    raw_args: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate tool arguments strictly against ``spec.parameters`` and apply defaults."""
    summary = _schema_summary(spec.parameters)
    if not isinstance(raw_args, dict):
        return None, err_result(
            f"Invalid arguments for '{spec.name}': expected a JSON object.",
            error_code=ERR_TOOL_SCHEMA,
            hint=f"Call '{spec.name}' with a JSON object matching ({summary}).",
        )
    prepared, err = _validate_value(raw_args, spec.parameters, spec.name)
    if err:
        return None, err_result(
            f"Invalid arguments for '{spec.name}': {err}.",
            error_code=ERR_TOOL_SCHEMA,
            hint=f"Retry '{spec.name}' with valid parameters ({summary}).",
        )
    return prepared, None


def _resolve_allowed_entries(ctx: ToolContext) -> list[Path]:
    entries: list[Path] = []
    if not ctx.allowed_paths:
        return entries
    for raw in ctx.allowed_paths:
        if not raw or "\x00" in raw:
            continue
        cand = Path(raw)
        if not cand.is_absolute():
            cand = ctx.workspace_root / cand
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if resolved.is_relative_to(ctx.workspace_root):
            entries.append(resolved)
    return entries


def is_path_within_allowed(
    resolved: Path,
    ctx: ToolContext,
    *,
    allow_ancestor: bool = False,
) -> bool:
    """Return True if ``resolved`` is permitted by ``ctx.allowed_paths``."""
    if ctx.allowed_paths is None:
        return True
    allowed_entries = _resolve_allowed_entries(ctx)
    for ap in allowed_entries:
        if resolved == ap or resolved.is_relative_to(ap):
            return True
        if allow_ancestor and ap.is_relative_to(resolved):
            return True
    return False


def resolve_workspace_path(
    raw_path: str,
    ctx: ToolContext,
    *,
    check_allowed: bool = True,
    allow_root: bool = False,
    allow_ancestor_fence: bool = False,
    for_mutation: bool = False,
    allow_scratch_read: bool = False,
) -> tuple[Path | None, str | None, dict[str, Any] | None]:
    """Resolve a path inside ``ctx.workspace_root`` (or ``@scratch/`` when enabled)."""
    if not isinstance(raw_path, str):
        return None, None, err_result(
            "Path must be a string.",
            error_code=ERR_TOOL_SCHEMA,
            hint="Pass a workspace-relative string path.",
        )
    if "\x00" in raw_path:
        return None, None, err_result(
            "Path contains a NUL byte.",
            error_code=ERR_PATH_SECURITY,
            hint="Provide a clean workspace-relative file path.",
        )
    stripped = raw_path.strip()
    if not stripped:
        if allow_root:
            stripped = "."
        else:
            return None, None, err_result(
                "Path cannot be empty.",
                error_code=ERR_TOOL_SCHEMA,
                hint="Provide a workspace-relative file path.",
            )

    if allow_scratch_read and not for_mutation:
        scratch_root = effective_scratch_dir(ctx)
        if stripped.startswith("@scratch/"):
            sub = stripped[len("@scratch/") :]
            if not sub.strip():
                return None, None, err_result(
                    "Scratch path cannot be empty after '@scratch/'.",
                    error_code=ERR_TOOL_SCHEMA,
                    hint="Pass the full '@scratch/...' log path returned by run_command.",
                )
            try:
                scratch_resolved = (scratch_root / sub).resolve()
            except OSError as exc:
                return None, None, err_result(
                    f"Could not resolve scratch path '{stripped}': {exc}.",
                    error_code=ERR_PATH_SECURITY,
                    hint="Provide a valid '@scratch/...' path.",
                )
            if not scratch_resolved.is_relative_to(scratch_root):
                return None, None, err_result(
                    f"Path '{stripped}' escapes the scratch directory.",
                    error_code=ERR_PATH_SECURITY,
                    hint="Use the exact '@scratch/...' path returned by run_command.",
                )
            rel_scratch = "@scratch/" + scratch_resolved.relative_to(scratch_root).as_posix()
            return scratch_resolved, rel_scratch, None

        cand_abs = Path(stripped)
        if cand_abs.is_absolute():
            try:
                abs_res = cand_abs.resolve()
            except OSError:
                abs_res = cand_abs
            if abs_res.is_relative_to(scratch_root) and not abs_res.is_relative_to(ctx.workspace_root):
                rel_scratch = "@scratch/" + abs_res.relative_to(scratch_root).as_posix()
                return abs_res, rel_scratch, None

    candidate = Path(stripped)
    if not candidate.is_absolute():
        candidate = ctx.workspace_root / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        return None, None, err_result(
            f"Could not resolve path '{stripped}': {exc}.",
            error_code=ERR_INVALID_TARGET,
            hint="Check the path spelling and retry with a valid workspace-relative path.",
        )

    if not resolved.is_relative_to(ctx.workspace_root):
        return None, None, err_result(
            f"Path '{stripped}' escapes the workspace root.",
            error_code=ERR_PATH_SECURITY,
            hint="Use a relative path that stays inside the workspace directory.",
        )

    if resolved == ctx.workspace_root and not allow_root:
        return None, None, err_result(
            "Path '.' refers to the workspace root directory, not a file.",
            error_code=ERR_INVALID_TARGET,
            hint="Pass a specific file path inside the workspace, or use list_files('.').",
        )

    rel_posix = "." if resolved == ctx.workspace_root else resolved.relative_to(ctx.workspace_root).as_posix()

    if ctx.block_secret_files and rel_posix != "." and is_secret_path(rel_posix):
        return None, None, err_result(
            f"Access to secret/credential file '{rel_posix}' is blocked by security policy.",
            error_code=ERR_PATH_SECURITY,
            hint="Do not read or modify .env, private key, or credential files.",
        )

    if for_mutation and rel_posix != "." and is_protected_path(rel_posix, ctx):
        return None, None, err_result(
            f"Path '{rel_posix}' is locked by the completion oracle and cannot be modified.",
            error_code=ERR_ORACLE_LOCKED,
            hint="Modify implementation files rather than protected test suites or linter configs.",
        )

    if check_allowed and not is_path_within_allowed(resolved, ctx, allow_ancestor=allow_ancestor_fence):
        allowed_list = list(ctx.allowed_paths or ())
        return None, None, err_result(
            f"Path '{rel_posix}' is outside your allowed_paths fence.",
            error_code=ERR_PATH_SECURITY,
            hint=f"Restrict operations to allowed paths: {allowed_list}.",
        )

    return resolved, rel_posix, None


def line_hash(line: str) -> str:
    """Compute the deterministic 2-hex-char Hashline digest for a single line."""
    return hashlib.blake2b(line.encode("utf-8"), digest_size=1).hexdigest()


def format_hashline(line_no: int, line: str) -> str:
    """Format one line with its 1-based line number and Hashline digest."""
    return f"{line_no}:{line_hash(line)}| {line}"


def format_hashline_range(lines: Sequence[str], start_line: int, end_line: int) -> str:
    """Format a 1-based inclusive line slice using Hashline prefixes."""
    if not lines or start_line > end_line:
        return ""
    s = max(1, start_line)
    e = min(len(lines), end_line)
    return "\n".join(format_hashline(idx, lines[idx - 1]) for idx in range(s, e + 1))


def parse_anchor(anchor: str) -> tuple[int, str] | None:
    """Parse a Hashline anchor like ``'42:a3'``, ``'L42:a3'``, or ``'42:a3| ...'`` into ``(line_number, lowercase_hex)``."""
    if not isinstance(anchor, str):
        return None
    head = anchor.split("|", 1)[0].strip()
    if head[:1] in {"L", "l"}:
        head = head[1:]
    if ":" not in head:
        return None
    line_part, hash_part = head.split(":", 1)
    if not line_part.isascii() or not line_part.isdigit():
        return None
    if len(hash_part) != 2 or any(ch not in "0123456789abcdefABCDEF" for ch in hash_part):
        return None
    return int(line_part), hash_part.lower()


def read_text_safe(path: Path, rel_posix: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Read a UTF-8 text file safely, preserving line endings and rejecting binary/invalid UTF-8."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, err_result(
            f"Failed to read '{rel_posix}': {exc}.",
            error_code=ERR_INFRA,
            hint="Verify the file exists and is readable using list_files.",
        )

    if b"\x00" in raw[:8192]:
        return None, err_result(
            f"Cannot read binary file '{rel_posix}' as UTF-8 text.",
            error_code=ERR_INVALID_TARGET,
            hint="Inspect only text source or config files with text tools.",
        )

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, err_result(
            f"File '{rel_posix}' is not valid UTF-8 text.",
            error_code=ERR_INVALID_TARGET,
            hint="Ensure the file is UTF-8 encoded text rather than binary or legacy encoding.",
        )

    crlf_count = raw.count(b"\r\n")
    lf_only = raw.count(b"\n") - crlf_count
    newline = "\r\n" if crlf_count > 0 and crlf_count >= lf_only else "\n"
    has_trailing_newline = True if not text else text.endswith(("\n", "\r"))
    lines = text.splitlines()

    return {
        "raw": raw,
        "text": text,
        "lines": lines,
        "newline": newline,
        "has_trailing_newline": has_trailing_newline,
    }, None


def maybe_backup(target: Path, rel_posix: str, ctx: ToolContext) -> str | None:
    """Create a backup snapshot in external scratch storage when ``ctx.enable_backups`` is enabled."""
    if not ctx.enable_backups or not target.exists() or not target.is_file():
        return None
    scratch_root = effective_scratch_dir(ctx)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    uniq = uuid.uuid4().hex[:6]
    dest = scratch_root / "backups" / f"{rel_posix}.{stamp}_{uniq}.bak"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, dest)
    return "@scratch/" + dest.relative_to(scratch_root).as_posix()


def atomic_write_bytes(target: Path, data: bytes) -> None:
    """Write ``data`` to ``target`` atomically via temp file + fsync + os.replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    tmp_file = None
    try:
        tmp_file = tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        )
        tmp_path = Path(tmp_file.name)
        tmp_file.write(data)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
        tmp_file.close()
        tmp_file = None
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if tmp_file is not None:
            try:
                tmp_file.close()
            except OSError:
                pass
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def check_syntax(rel_posix: str, content: str) -> str | None:
    """Run a fast, non-blocking syntax check for supported file types."""
    suffix = Path(rel_posix).suffix.casefold()
    if suffix == ".py":
        try:
            ast.parse(content, filename=rel_posix)
        except SyntaxError as exc:
            line_info = f"line {exc.lineno}" if exc.lineno else "unknown line"
            return f"Python SyntaxError at {line_info}: {exc.msg}"
        return None
    if suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            return f"JSONDecodeError at line {exc.lineno}, col {exc.colno}: {exc.msg}"
        return None
    if suffix in {".js", ".mjs", ".cjs"}:
        node = shutil.which("node")
        if not node:
            return None
        try:
            proc = subprocess.run(
                [node, "--check", "-"],
                input=content,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=None,
                capture_output=True,
                timeout=5,
            )
            if proc.returncode != 0:
                msg = (proc.stderr or proc.stdout or "").strip()
                return f"JavaScript syntax check failed: {msg[:500]}"
        except (OSError, subprocess.TimeoutExpired):
            return None
    return None


@dataclass(frozen=True)
class _GitignoreRule:
    negated: bool
    dir_only: bool
    anchored: bool
    has_slash: bool
    pattern: str


class GitignoreMatcher:
    """Pure-stdlib matcher for default ignored directories and ``.gitignore`` rules."""

    def __init__(self, rules: Sequence[_GitignoreRule]) -> None:
        self._rules = tuple(rules)

    def is_ignored(self, rel_posix: str, *, is_dir: bool) -> bool:
        parts = rel_posix.split("/")
        if any(part in DEFAULT_IGNORED_DIRS or ".backup_" in part for part in parts):
            return True
        name = parts[-1]
        ignored = False
        for rule in self._rules:
            if rule.dir_only and not is_dir:
                matched = False
                for i in range(len(parts) - 1):
                    sub = "/".join(parts[: i + 1])
                    if self._match_rule(rule, sub, parts[i]):
                        matched = True
                        break
            else:
                matched = self._match_rule(rule, rel_posix, name)
            if matched:
                ignored = not rule.negated
        return ignored

    @staticmethod
    def _match_rule(rule: _GitignoreRule, rel_posix: str, basename: str) -> bool:
        pat = rule.pattern
        if rule.anchored or rule.has_slash:
            if fnmatch.fnmatch(rel_posix, pat):
                return True
            if pat.startswith("**/") and fnmatch.fnmatch(rel_posix, pat[3:]):
                return True
            return False
        return fnmatch.fnmatch(basename, pat)


def load_gitignore_matcher(workspace_root: Path) -> GitignoreMatcher:
    """Load rules from ``workspace_root/.gitignore`` if present."""
    gitignore_path = workspace_root / ".gitignore"
    rules: list[_GitignoreRule] = []
    if gitignore_path.is_file():
        try:
            raw_lines = gitignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            raw_lines = []
        for raw in raw_lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = False
            if line.startswith("!"):
                negated = True
                line = line[1:]
            dir_only = line.endswith("/")
            if dir_only:
                line = line.rstrip("/")
            anchored = line.startswith("/")
            if anchored:
                line = line.lstrip("/")
            if not line:
                continue
            has_slash = "/" in line
            rules.append(
                _GitignoreRule(
                    negated=negated,
                    dir_only=dir_only,
                    anchored=anchored,
                    has_slash=has_slash,
                    pattern=line,
                )
            )
    return GitignoreMatcher(rules)
