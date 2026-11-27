"""Read and discovery tool units: ``read_file``, ``list_files``, and ``search_code``."""

from __future__ import annotations

import fnmatch
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from .base import (
    ERR_INVALID_TARGET,
    ERR_NOT_FOUND,
    ERR_TOOL_SCHEMA,
    ToolContext,
    ToolSpec,
    err_result,
    format_hashline,
    format_hashline_range,
    is_path_within_allowed,
    is_secret_path,
    line_hash,
    load_gitignore_matcher,
    ok_result,
    read_text_safe,
    resolve_workspace_path,
)

_MAX_MATCH_LINE_CHARS = 300


def _normalize_glob_pattern(pattern: str) -> str:
    pat = (pattern or "").strip().replace("\\", "/")
    if pat.startswith("./"):
        pat = pat[2:]
    return pat


@lru_cache(maxsize=256)
def _compile_path_glob(pat: str) -> re.Pattern[str]:
    out = ["^"]
    i = 0
    n = len(pat)
    while i < n:
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        elif pat[i] == "[":
            end = pat.find("]", i + 1)
            if end != -1 and "/" not in pat[i:end]:
                inner = pat[i + 1 : end]
                if inner.startswith("!"):
                    inner = "^" + inner[1:]
                out.append(f"[{inner}]")
                i = end + 1
            else:
                out.append(r"\[")
                i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    out.append("$")
    flags = re.IGNORECASE if os.name == "nt" else 0
    return re.compile("".join(out), flags)


def _matches_glob(rel_posix: str, basename: str, pattern: str) -> bool:
    pat = _normalize_glob_pattern(pattern)
    if not pat or pat == "*":
        return True
    if "/" not in pat:
        return fnmatch.fnmatch(basename, pat)
    return bool(_compile_path_glob(pat).fullmatch(rel_posix))


def _handle_read_file(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    resolved, rel_posix, err = resolve_workspace_path(
        args["path"],
        ctx,
        check_allowed=True,
        allow_root=False,
        allow_scratch_read=True,
    )
    if err is not None or resolved is None or rel_posix is None:
        return err  # type: ignore[return-value]

    if not resolved.exists():
        return err_result(
            f"File '{rel_posix}' does not exist.",
            error_code=ERR_NOT_FOUND,
            hint="Call list_files() to check available files in the workspace.",
        )
    if resolved.is_dir():
        return err_result(
            f"Path '{rel_posix}' is a directory, not a file.",
            error_code=ERR_INVALID_TARGET,
            hint=f"Call list_files(path={rel_posix!r}) to inspect directory entries.",
        )

    info, read_err = read_text_safe(resolved, rel_posix)
    if read_err is not None or info is None:
        return read_err  # type: ignore[return-value]

    lines: list[str] = info["lines"]
    total_lines = len(lines)

    if total_lines == 0:
        return ok_result(
            {
                "path": rel_posix,
                "start_line": 0,
                "end_line": 0,
                "total_lines": 0,
                "content": "",
            },
            truncated=False,
            hint=(
                "File is empty (0 lines). Use write_file(overwrite=True) or "
                "edit_file(operation='insert_after', start_anchor='0:00', content=...) to add content."
            ),
        )

    start_line: int = args.get("start_line", 1)
    end_line_arg: int | None = args.get("end_line")

    if start_line > total_lines:
        suggested_end = min(total_lines, max(1, ctx.max_read_lines))
        return err_result(
            f"start_line {start_line} exceeds total lines ({total_lines}) in '{rel_posix}'.",
            error_code=ERR_TOOL_SCHEMA,
            hint=f"Call read_file(path={rel_posix!r}, start_line=1, end_line={suggested_end}).",
        )
    if end_line_arg is not None and end_line_arg < start_line:
        return err_result(
            f"Invalid line range {start_line}-{end_line_arg} for '{rel_posix}'.",
            error_code=ERR_TOOL_SCHEMA,
            hint=f"Ensure end_line >= start_line (1..{total_lines}).",
        )

    requested_end = total_lines if end_line_arg is None else min(end_line_arg, total_lines)
    max_lines = max(1, ctx.max_read_lines)
    max_chars = max(64, ctx.max_output_chars)

    line_cap_end = min(requested_end, start_line + max_lines - 1)
    capped_by_lines = line_cap_end < requested_end

    rendered: list[str] = []
    char_count = 0
    capped_by_chars = False
    actual_end = start_line - 1

    for idx in range(start_line, line_cap_end + 1):
        formatted = format_hashline(idx, lines[idx - 1])
        added_len = len(formatted) + (1 if rendered else 0)
        if char_count + added_len > max_chars:
            if not rendered:
                clip = max(1, max_chars - 3)
                rendered.append(formatted[:clip] + "...")
                actual_end = idx
            capped_by_chars = True
            break
        rendered.append(formatted)
        char_count += added_len
        actual_end = idx

    truncated = capped_by_lines or capped_by_chars
    hint: str | None = None
    if truncated:
        if actual_end < total_lines:
            next_start = actual_end + 1
            next_end = min(total_lines, next_start + max_lines - 1)
            hint = (
                f"Showing lines {start_line}-{actual_end} of {total_lines}. "
                f"Call read_file(path={rel_posix!r}, start_line={next_start}, end_line={next_end}) to continue."
            )
        else:
            hint = f"Output truncated at {max_chars} chars (line {actual_end} of {total_lines})."

    return ok_result(
        {
            "path": rel_posix,
            "start_line": start_line,
            "end_line": actual_end,
            "total_lines": total_lines,
            "content": "\n".join(rendered),
        },
        truncated=truncated,
        hint=hint,
    )


def _handle_list_files(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    resolved, rel_posix, err = resolve_workspace_path(
        args.get("path", "."),
        ctx,
        check_allowed=True,
        allow_root=True,
        allow_ancestor_fence=True,
    )
    if err is not None or resolved is None or rel_posix is None:
        return err  # type: ignore[return-value]

    if not resolved.exists():
        return err_result(
            f"Directory '{rel_posix}' does not exist.",
            error_code=ERR_NOT_FOUND,
            hint="Call list_files(path='.') to inspect the workspace root.",
        )
    if resolved.is_file():
        return err_result(
            f"Path '{rel_posix}' is a file, not a directory.",
            error_code=ERR_INVALID_TARGET,
            hint=f"Call read_file(path={rel_posix!r}) to inspect this file.",
        )

    pattern: str = args.get("pattern", "*") or "*"
    max_depth: int = args.get("max_depth", 3)
    matcher = load_gitignore_matcher(ctx.workspace_root)

    matched_entries: list[str] = []

    def _walk(current_dir: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(current_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
        except OSError:
            return
        for child in children:
            try:
                resolved_child = child.resolve()
            except OSError:
                continue
            if not resolved_child.is_relative_to(ctx.workspace_root):
                continue
            child_rel = resolved_child.relative_to(ctx.workspace_root).as_posix()
            is_dir = resolved_child.is_dir()
            if matcher.is_ignored(child_rel, is_dir=is_dir):
                continue
            if ctx.block_secret_files and not is_dir and is_secret_path(child_rel):
                continue
            if not is_path_within_allowed(resolved_child, ctx, allow_ancestor=is_dir):
                continue
            if is_path_within_allowed(resolved_child, ctx, allow_ancestor=False):
                if _matches_glob(child_rel, child.name, pattern):
                    matched_entries.append(f"{child_rel}/" if is_dir else child_rel)
            if is_dir and depth < max_depth:
                _walk(resolved_child, depth + 1)

    _walk(resolved, 1)
    matched_entries.sort()
    total_found = len(matched_entries)
    max_entries = max(1, ctx.max_list_entries)
    truncated = total_found > max_entries
    entries = matched_entries[:max_entries]

    hint: str | None = None
    if truncated:
        hint = (
            f"Showing {len(entries)} of {total_found} matching entries. "
            "Pass a narrower 'path', 'pattern', or smaller 'max_depth' to refine."
        )

    return ok_result(
        {
            "path": rel_posix,
            "entries": entries,
            "count": len(entries),
            "total_found": total_found,
        },
        truncated=truncated,
        hint=hint,
    )


def _iter_searchable_files(
    target: Path,
    ctx: ToolContext,
    *,
    file_glob: str,
) -> list[tuple[Path, str]]:
    matcher = load_gitignore_matcher(ctx.workspace_root)
    if target.is_file():
        rel = target.relative_to(ctx.workspace_root).as_posix()
        if ctx.block_secret_files and is_secret_path(rel):
            return []
        if file_glob and not _matches_glob(rel, target.name, file_glob):
            return []
        return [(target, rel)]

    files: list[tuple[Path, str]] = []
    for root, dirs, filenames in os.walk(target):
        root_path = Path(root)
        kept_dirs: list[str] = []
        for d in sorted(dirs):
            d_path = root_path / d
            try:
                d_res = d_path.resolve()
            except OSError:
                continue
            if not d_res.is_relative_to(ctx.workspace_root):
                continue
            d_rel = d_res.relative_to(ctx.workspace_root).as_posix()
            if matcher.is_ignored(d_rel, is_dir=True):
                continue
            if not is_path_within_allowed(d_res, ctx, allow_ancestor=True):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for fname in sorted(filenames):
            f_path = root_path / fname
            try:
                f_res = f_path.resolve()
            except OSError:
                continue
            if not f_res.is_relative_to(ctx.workspace_root) or not f_res.is_file():
                continue
            f_rel = f_res.relative_to(ctx.workspace_root).as_posix()
            if matcher.is_ignored(f_rel, is_dir=False):
                continue
            if ctx.block_secret_files and is_secret_path(f_rel):
                continue
            if not is_path_within_allowed(f_res, ctx, allow_ancestor=False):
                continue
            if file_glob and not _matches_glob(f_rel, fname, file_glob):
                continue
            files.append((f_res, f_rel))
    files.sort(key=lambda item: item[1])
    return files


def _search_python(
    target: Path,
    ctx: ToolContext,
    *,
    pattern: re.Pattern[str],
    file_glob: str,
    context_lines: int = 0,
) -> tuple[list[dict[str, Any]], int, bool]:
    files = _iter_searchable_files(target, ctx, file_glob=file_glob)
    max_matches = max(1, ctx.max_search_matches)
    max_chars = max(256, ctx.max_output_chars)

    matches: list[dict[str, Any]] = []
    total_matches = 0
    total_chars = 0
    truncated = False

    for file_path, rel_posix in files:
        try:
            raw = file_path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        file_lines = text.splitlines()
        for idx, line in enumerate(file_lines, start=1):
            if pattern.search(line):
                total_matches += 1
                if len(matches) < max_matches and not truncated:
                    clipped = line[:_MAX_MATCH_LINE_CHARS] + ("..." if len(line) > _MAX_MATCH_LINE_CHARS else "")
                    entry: dict[str, Any] = {
                        "path": rel_posix,
                        "line": idx,
                        "anchor": f"{idx}:{line_hash(line)}",
                        "text": clipped,
                    }
                    est_chars = len(rel_posix) + len(clipped) + 24
                    if context_lines > 0:
                        ctx_start = max(1, idx - context_lines)
                        ctx_end = min(len(file_lines), idx + context_lines)
                        ctx_block = format_hashline_range(file_lines, ctx_start, ctx_end)
                        entry["context"] = ctx_block
                        est_chars += len(ctx_block) + 16
                    if matches and total_chars + est_chars > max_chars:
                        truncated = True
                    else:
                        matches.append(entry)
                        total_chars += est_chars
                else:
                    truncated = True

    return matches, total_matches, truncated


def _read_lines_cached(
    file_path: Path,
    rel_posix: str,
    cache: dict[str, list[str] | None],
) -> list[str] | None:
    if rel_posix in cache:
        return cache[rel_posix]
    try:
        raw = file_path.read_bytes()
    except OSError:
        cache[rel_posix] = None
        return None
    if b"\x00" in raw[:8192]:
        cache[rel_posix] = None
        return None
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        cache[rel_posix] = None
        return None
    cache[rel_posix] = lines
    return lines


def _search_ripgrep(
    rg_bin: str,
    target: Path,
    rel_target: str,
    ctx: ToolContext,
    *,
    query: str,
    file_glob: str,
    is_regex: bool,
    case_sensitive: bool,
    context_lines: int = 0,
) -> tuple[list[dict[str, Any]], int, bool] | None:
    cmd = [rg_bin, "--json", "--no-messages", "--hidden"]
    if not is_regex:
        cmd.append("-F")
    if not case_sensitive:
        cmd.append("-i")
    norm_fg = _normalize_glob_pattern(file_glob)
    if norm_fg:
        if "/" not in norm_fg:
            cmd.extend(["-g", norm_fg])
        elif norm_fg.startswith("**/") and "/" not in norm_fg[3:]:
            cmd.extend(["-g", norm_fg[3:]])
    for ignored in (".git", ".hivo", ".agent_backups", ".agent_runs", ".agent_evidence"):
        cmd.extend(["-g", f"!{ignored}/**"])
    rg_target = "." if rel_target in {"", "."} else rel_target
    cmd.extend(["--", query, rg_target])

    try:
        proc = subprocess.run(
            cmd,
            cwd=ctx.workspace_root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(5, min(ctx.timeout_sec, 30)),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if proc.returncode not in (0, 1):
        return None

    max_matches = max(1, ctx.max_search_matches)
    max_chars = max(256, ctx.max_output_chars)
    matches: list[dict[str, Any]] = []
    file_lines_cache: dict[str, list[str] | None] = {}
    total_matches = 0
    total_chars = 0
    truncated = False

    for raw_line in proc.stdout.splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data") or {}
        path_text = (data.get("path") or {}).get("text")
        line_no = data.get("line_number")
        line_raw = (data.get("lines") or {}).get("text")
        if not isinstance(path_text, str) or not isinstance(line_no, int) or not isinstance(line_raw, str):
            continue
        resolved = Path(path_text)
        if not resolved.is_absolute():
            resolved = ctx.workspace_root / resolved
        try:
            resolved = resolved.resolve()
        except OSError:
            continue
        if not resolved.is_relative_to(ctx.workspace_root):
            continue
        rel_posix = resolved.relative_to(ctx.workspace_root).as_posix()
        if ctx.block_secret_files and is_secret_path(rel_posix):
            continue
        if file_glob and not _matches_glob(rel_posix, resolved.name, file_glob):
            continue
        line_clean = line_raw.rstrip("\r\n")
        total_matches += 1
        if len(matches) < max_matches and not truncated:
            clipped = line_clean[:_MAX_MATCH_LINE_CHARS] + ("..." if len(line_clean) > _MAX_MATCH_LINE_CHARS else "")
            entry: dict[str, Any] = {
                "path": rel_posix,
                "line": line_no,
                "anchor": f"{line_no}:{line_hash(line_clean)}",
                "text": clipped,
            }
            est_chars = len(rel_posix) + len(clipped) + 24
            if context_lines > 0:
                cached_lines = _read_lines_cached(resolved, rel_posix, file_lines_cache)
                if cached_lines:
                    ctx_start = max(1, line_no - context_lines)
                    ctx_end = min(len(cached_lines), line_no + context_lines)
                    ctx_block = format_hashline_range(cached_lines, ctx_start, ctx_end)
                    entry["context"] = ctx_block
                    est_chars += len(ctx_block) + 16
            if matches and total_chars + est_chars > max_chars:
                truncated = True
            else:
                matches.append(entry)
                total_chars += est_chars
        else:
            truncated = True

    return matches, total_matches, truncated


def _handle_search_code(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    query: str = args["query"]
    if not query:
        return err_result(
            "Search query cannot be empty.",
            error_code=ERR_TOOL_SCHEMA,
            hint="Provide a non-empty text or regex pattern in 'query'.",
        )

    is_regex: bool = args.get("is_regex", False)
    case_sensitive: bool = args.get("case_sensitive", True)
    file_glob: str = args.get("file_glob", "") or ""
    context_lines: int = args.get("context_lines", 0)

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(query if is_regex else re.escape(query), flags)
    except re.error as exc:
        return err_result(
            f"Invalid regular expression '{query}': {exc}.",
            error_code=ERR_TOOL_SCHEMA,
            hint="Set is_regex=False for literal search or fix the regular expression.",
        )

    resolved, rel_posix, err = resolve_workspace_path(
        args.get("path", "."),
        ctx,
        check_allowed=True,
        allow_root=True,
        allow_ancestor_fence=True,
    )
    if err is not None or resolved is None or rel_posix is None:
        return err  # type: ignore[return-value]

    if not resolved.exists():
        return err_result(
            f"Search path '{rel_posix}' does not exist.",
            error_code=ERR_NOT_FOUND,
            hint="Call list_files(path='.') to inspect available paths.",
        )

    matches: list[dict[str, Any]]
    total_matches: int
    truncated: bool

    rg_bin = shutil.which("rg")
    used_rg = False
    if rg_bin and ctx.allowed_paths is None:
        rg_res = _search_ripgrep(
            rg_bin,
            resolved,
            rel_posix,
            ctx,
            query=query,
            file_glob=file_glob,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            context_lines=context_lines,
        )
        if rg_res is not None:
            matches, total_matches, truncated = rg_res
            used_rg = True

    if not used_rg:
        matches, total_matches, truncated = _search_python(
            resolved,
            ctx,
            pattern=compiled,
            file_glob=file_glob,
            context_lines=context_lines,
        )

    hint: str | None = None
    if truncated:
        hint = (
            f"Showing {len(matches)} of {total_matches} matches. "
            "Narrow your query, pass a specific 'path', or filter with 'file_glob'."
        )

    return ok_result(
        {
            "query": query,
            "path": rel_posix,
            "matches": matches,
            "match_count": len(matches),
            "total_matches": total_matches,
        },
        truncated=truncated,
        hint=hint,
    )


READ_FILE_SPEC = ToolSpec(
    name="read_file",
    description=(
        "Read a bounded line range of a UTF-8 file (or '@scratch/...' offloaded log) with Hashline anchors "
        "('line:hash| text'). Always inspect lines before calling edit_file."
    ),
    effect="read",
    model_tier="slm_safe",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path or '@scratch/...' log path."},
            "start_line": {
                "type": "integer",
                "minimum": 1,
                "default": 1,
                "description": "1-based first line to read (default 1).",
            },
            "end_line": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional 1-based inclusive last line to read.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    handler=_handle_read_file,
)

LIST_FILES_SPEC = ToolSpec(
    name="list_files",
    description="List workspace files and directories respecting .gitignore up to max_depth.",
    effect="read",
    model_tier="slm_safe",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "default": ".",
                "description": "Workspace-relative directory to list (default '.').",
            },
            "pattern": {
                "type": "string",
                "default": "*",
                "description": "Optional glob pattern to filter entries (default '*').",
            },
            "max_depth": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 3,
                "description": "Maximum directory depth to traverse (1..10, default 3).",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
    handler=_handle_list_files,
)

SEARCH_CODE_SPEC = ToolSpec(
    name="search_code",
    description="Search UTF-8 source files for a literal string (default) or regex and return matching Hashline anchors.",
    effect="read",
    model_tier="slm_safe",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search text or regex pattern."},
            "path": {
                "type": "string",
                "default": ".",
                "description": "Workspace-relative directory or file to search (default '.').",
            },
            "file_glob": {
                "type": "string",
                "default": "",
                "description": "Optional glob filter such as '*.py'.",
            },
            "is_regex": {
                "type": "boolean",
                "default": False,
                "description": "Set true for regex search; false (default) searches literally.",
            },
            "case_sensitive": {
                "type": "boolean",
                "default": True,
                "description": "Whether search is case-sensitive (default true).",
            },
            "context_lines": {
                "type": "integer",
                "minimum": 0,
                "maximum": 5,
                "default": 0,
                "description": "Optional surrounding context lines (0-5) formatted with Hashlines.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    handler=_handle_search_code,
)
