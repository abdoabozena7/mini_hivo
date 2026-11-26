"""Subprocess execution tool unit: ``run_command``."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
from typing import Any, Mapping
import uuid

from .base import (
    ERR_COMMAND_REFUSED,
    ERR_COMMAND_TIMEOUT,
    ERR_INFRA,
    ERR_INVALID_TARGET,
    ToolContext,
    ToolSpec,
    atomic_write_bytes,
    effective_scratch_dir,
    err_result,
    is_secret_path,
    ok_result,
    resolve_workspace_path,
)

DEFAULT_ALLOWED_COMMANDS: frozenset[str] = frozenset({
    "python",
    "python3",
    "py",
    "pytest",
    "ruff",
    "mypy",
    "flake8",
    "node",
    "npm",
    "npx",
    "git",
    "g++",
    "clang++",
    "tsc",
    "cargo",
    "go",
})

_READ_ONLY_GIT_SUBCOMMANDS: frozenset[str] = frozenset({
    "status",
    "diff",
    "log",
    "show",
    "ls-files",
    "rev-parse",
    "branch",
})

_SECRET_ENV_EXACT: frozenset[str] = frozenset({
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "DATABASE_URL",
})
_SECRET_ENV_SUFFIXES: tuple[str, ...] = (
    "_API_KEY",
    "_SECRET",
    "_SECRET_KEY",
    "_TOKEN",
    "_PASSWORD",
    "_PRIVATE_KEY",
)

_HEAD_LINES = 40
_TAIL_LINES = 60


def build_sanitized_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a non-interactive environment dict with host secrets scrubbed."""
    source = os.environ if base_env is None else base_env
    cleaned: dict[str, str] = {}
    for key, val in source.items():
        upper = key.upper()
        if upper in _SECRET_ENV_EXACT or upper.endswith(_SECRET_ENV_SUFFIXES):
            continue
        cleaned[key] = val

    cleaned["CI"] = "true"
    cleaned["GIT_PAGER"] = "cat"
    cleaned["PAGER"] = "cat"
    cleaned["GIT_TERMINAL_PROMPT"] = "0"
    cleaned["PIP_NO_INPUT"] = "1"
    cleaned["PYTHONUNBUFFERED"] = "1"
    cleaned["PYTHONIOENCODING"] = "utf-8"
    cleaned["PYTHONDONTWRITEBYTECODE"] = "1"
    return cleaned


def _find_unquoted_shell_token(command: str) -> str | None:
    """Detect shell composition/redirection tokens outside single/double quotes."""
    in_single = False
    in_double = False
    escaped = False
    n = len(command)
    i = 0
    while i < n:
        ch = command[i]
        if escaped:
            escaped = False
            i += 1
            continue
        if ch == "\\" and in_double:
            escaped = True
            i += 1
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if not in_single and not in_double:
            two = command[i : i + 2]
            if two in {"&&", "||", "$(", ">>", "<<"}:
                return two
            if ch in {";", "|", ">", "<", "`"}:
                return ch
        i += 1
    return None


def _strip_outer_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    return token


def _validate_arg_path_and_secret(
    tok: str,
    resolved_cwd: Path,
    ctx: ToolContext,
) -> str | None:
    if not tok or "://" in tok:
        return None
    candidate = Path(tok)
    looks_like_path = (
        candidate.is_absolute()
        or ".." in candidate.parts
        or "/" in tok
        or "\\" in tok
    )
    resolved_arg: Path | None = None
    try:
        resolved_arg = (
            candidate.resolve()
            if candidate.is_absolute()
            else (resolved_cwd / candidate).resolve()
        )
    except OSError:
        if looks_like_path:
            return f"could not resolve path argument: {tok}"

    if looks_like_path:
        assert resolved_arg is not None
        if not resolved_arg.is_relative_to(ctx.workspace_root):
            return f"path argument escapes the workspace: {tok}"

    if ctx.block_secret_files:
        if is_secret_path(tok):
            return f"secret file argument '{tok}' is blocked by workspace policy"
        if resolved_arg is not None and resolved_arg.is_relative_to(ctx.workspace_root):
            rel_posix = resolved_arg.relative_to(ctx.workspace_root).as_posix()
            if is_secret_path(rel_posix):
                return f"secret file argument '{tok}' is blocked by workspace policy"
    return None


def _validate_command(
    command: str,
    resolved_cwd: Path,
    ctx: ToolContext,
) -> tuple[list[str] | None, str | None]:
    if not command.strip():
        return None, "command cannot be empty"
    if any(ch in command for ch in ("\n", "\r", "\x00")):
        return None, "control characters and multiline shell scripts are not allowed"

    shell_tok = _find_unquoted_shell_token(command)
    if shell_tok is not None:
        return None, f"shell composition/redirection token '{shell_tok}' is not allowed"

    try:
        parts = shlex.split(command, posix=(os.name != "nt"))
    except ValueError as exc:
        return None, f"could not parse command: {exc}"

    if os.name == "nt":
        parts = [_strip_outer_quotes(p) for p in parts]

    if not parts or not parts[0]:
        return None, "empty command"

    executable = Path(parts[0]).stem.lower()
    allowed = (
        {c.lower() for c in ctx.allowed_commands}
        if ctx.allowed_commands is not None
        else set(DEFAULT_ALLOWED_COMMANDS)
    )
    if executable not in allowed:
        return None, f"executable '{executable}' is not in the allowed commands list"

    if executable in {"python", "python3", "py"}:
        if any(p == "-c" or p.startswith("-c") for p in parts[1:]):
            return None, "inline Python (-c) is not allowed"
        parts[0] = sys.executable

    if executable == "node" and any(p in {"-e", "--eval"} for p in parts[1:]):
        return None, "inline Node.js (-e/--eval) is not allowed"

    if executable == "git":
        subcommand = next((p for p in parts[1:] if not p.startswith("-")), "")
        if subcommand not in _READ_ONLY_GIT_SUBCOMMANDS:
            return None, f"git subcommand '{subcommand}' is not allowed (read-only only)"
        if subcommand == "branch" and any(p in {"-d", "-D", "-m", "-M", "-f", "--delete", "--force"} for p in parts[1:]):
            return None, "mutating git branch flags are not allowed"

    if executable == "npm":
        subcommand = next((p for p in parts[1:] if not p.startswith("-")), "")
        if subcommand in {"install", "i", "uninstall", "remove", "publish", "link", "ci"}:
            return None, f"npm subcommand '{subcommand}' is not allowed"

    for part in parts[1:]:
        if part.startswith("-"):
            if "=" in part:
                _, rhs = part.split("=", 1)
                rhs = _strip_outer_quotes(rhs)
                arg_err = _validate_arg_path_and_secret(rhs, resolved_cwd, ctx)
                if arg_err is not None:
                    return None, arg_err
            continue
        if "://" in part:
            continue
        if executable == "git" and ":" in part and not (len(part) >= 2 and part[1] == ":" and part[0].isalpha()):
            _, git_path = part.split(":", 1)
            git_err = _validate_arg_path_and_secret(git_path, resolved_cwd, ctx)
            if git_err is not None:
                return None, git_err
        arg_err = _validate_arg_path_and_secret(part, resolved_cwd, ctx)
        if arg_err is not None:
            return None, arg_err

    return parts, None


def _truncate_stream(text: str, max_chars: int) -> tuple[str, bool]:
    if not text:
        return "", False
    lines = text.splitlines()
    truncated = False
    if len(lines) > _HEAD_LINES + _TAIL_LINES:
        omitted = len(lines) - _HEAD_LINES - _TAIL_LINES
        lines = (
            lines[:_HEAD_LINES]
            + [f"... [{omitted} lines omitted; see log_path] ..."]
            + lines[-_TAIL_LINES:]
        )
        truncated = True
    joined = "\n".join(lines)
    if len(joined) > max_chars:
        half = max(64, (max_chars - 48) // 2)
        joined = (
            joined[:half]
            + "\n... [output truncated by char cap; see log_path] ...\n"
            + joined[-half:]
        )
        truncated = True
    return joined, truncated


def _write_overflow_log(
    command: str,
    stdout_text: str,
    stderr_text: str,
    ctx: ToolContext,
) -> str | None:
    scratch_root = effective_scratch_dir(ctx)
    log_dir = scratch_root / "tool_logs"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    uniq = uuid.uuid4().hex[:8]
    log_file = log_dir / f"run_command_{stamp}_{uniq}.log"
    payload = (
        f"COMMAND: {command}\n"
        f"=== STDOUT ===\n{stdout_text}\n"
        f"=== STDERR ===\n{stderr_text}\n"
    )
    try:
        atomic_write_bytes(log_file, payload.encode("utf-8", errors="replace"))
    except OSError:
        return None
    if log_file.is_relative_to(scratch_root):
        return "@scratch/" + log_file.relative_to(scratch_root).as_posix()
    return str(log_file)


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if taskkill:
            try:
                subprocess.run(
                    [taskkill, "/F", "/T", "/PID", str(proc.pid)],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass


def _handle_run_command(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    resolved_cwd, rel_cwd, cwd_err = resolve_workspace_path(
        args.get("cwd", "."),
        ctx,
        check_allowed=False,
        allow_root=True,
    )
    if cwd_err is not None or resolved_cwd is None or rel_cwd is None:
        return cwd_err  # type: ignore[return-value]

    if not resolved_cwd.exists() or not resolved_cwd.is_dir():
        return err_result(
            f"Working directory '{rel_cwd}' does not exist or is not a directory.",
            error_code=ERR_INVALID_TARGET,
            hint="Pass cwd='.' or an existing directory path inside the workspace.",
        )

    command: str = args["command"]
    parts, cmd_err = _validate_command(command, resolved_cwd, ctx)
    if cmd_err or parts is None:
        return err_result(
            f"Command refused: {cmd_err}.",
            error_code=ERR_COMMAND_REFUSED,
            hint="Use an allowlisted non-interactive command without shell operators (e.g., pytest, python script.py).",
        )

    req_timeout: int = args.get("timeout_sec", 0)
    max_ctx_timeout = max(1, ctx.timeout_sec)
    eff_timeout = max_ctx_timeout if req_timeout <= 0 else min(req_timeout, max_ctx_timeout)

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    start_new_session = os.name != "nt"

    try:
        proc = subprocess.Popen(
            parts,
            shell=False,
            cwd=resolved_cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=build_sanitized_env(),
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
    except OSError as exc:
        return err_result(
            f"Failed to launch command '{parts[0]}': {exc}.",
            error_code=ERR_INFRA,
            hint="Verify the executable is installed and available on PATH.",
        )

    timed_out = False
    try:
        stdout_raw, stderr_raw = proc.communicate(timeout=eff_timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(proc)
        try:
            stdout_raw, stderr_raw = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()
            stdout_raw, stderr_raw = "", ""

    per_stream_chars = max(256, ctx.max_output_chars // 2)
    out_preview, out_trunc = _truncate_stream(stdout_raw, per_stream_chars)
    err_preview, err_trunc = _truncate_stream(stderr_raw, per_stream_chars)
    was_truncated = out_trunc or err_trunc

    log_path: str | None = None
    if was_truncated or (timed_out and (stdout_raw or stderr_raw)):
        log_path = _write_overflow_log(command, stdout_raw, stderr_raw, ctx)

    data: dict[str, Any] = {
        "command": command,
        "cwd": rel_cwd,
        "exit_code": None if timed_out else proc.returncode,
        "timed_out": timed_out,
        "stdout": out_preview,
        "stderr": err_preview,
        "log_path": log_path,
    }

    if timed_out:
        hint = (
            f"Command timed out after {eff_timeout}s and its process tree was terminated."
            + (f" Full partial logs saved to '{log_path}'." if log_path else "")
        )
        return err_result(
            f"Command timed out after {eff_timeout}s.",
            error_code=ERR_COMMAND_TIMEOUT,
            data=data,
            hint=hint,
            truncated=was_truncated,
        )

    hint_parts: list[str] = []
    if proc.returncode != 0:
        hint_parts.append(f"Command exited with code {proc.returncode}. Inspect stderr/stdout for failure details.")
    if was_truncated and log_path:
        hint_parts.append(f"Output was truncated. Use read_file(path={log_path!r}) or search_code to inspect full logs.")
    hint = " ".join(hint_parts) if hint_parts else None

    return ok_result(data, truncated=was_truncated, hint=hint)


RUN_COMMAND_SPEC = ToolSpec(
    name="run_command",
    description=(
        "Execute an allowlisted non-interactive verification/build command inside the workspace "
        "with scrubbed env, timeout tree-kill, separate stdout/stderr, and external @scratch/ log offloading."
    ),
    effect="exec",
    model_tier="orchestrator_only",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command line to execute (no shell chaining operators)."},
            "cwd": {
                "type": "string",
                "default": ".",
                "description": "Workspace-relative working directory (default '.').",
            },
            "timeout_sec": {
                "type": "integer",
                "minimum": 0,
                "maximum": 600,
                "default": 0,
                "description": "Timeout in seconds (0 uses context default, capped at context timeout).",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    handler=_handle_run_command,
)
