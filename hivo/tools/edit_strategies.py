"""Swappable edit-format tool units for calibrated worker profiles."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .base import (
    ERR_EDIT_APPLY,
    ERR_INFRA,
    ERR_INVALID_TARGET,
    ERR_NOT_FOUND,
    ToolContext,
    ToolSpec,
    atomic_write_bytes,
    err_result,
    format_hashline_range,
    maybe_backup,
    ok_result,
    read_text_safe,
    resolve_workspace_path,
)
from .fs_write import EDIT_FILE_SPEC, WRITE_FILE_SPEC, _split_replacement_lines
from .hooks import run_post_edit_sensors

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _normalize_to_file_newline(text: str, newline: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)


def _save_and_sense(
    tool_name: str,
    resolved: Any,
    rel_posix: str,
    final_text: str,
    ctx: ToolContext,
    extra_data: dict[str, Any],
    *,
    focus_start: int | None = None,
    focus_end: int | None = None,
) -> dict[str, Any]:
    try:
        maybe_backup(resolved, rel_posix, ctx)
        atomic_write_bytes(resolved, final_text.encode("utf-8"))
    except OSError as exc:
        return err_result(
            f"Failed to write '{rel_posix}': {exc}.",
            error_code=ERR_INFRA,
            hint="Verify workspace permissions and retry.",
        )

    updated_lines = final_text.splitlines()
    if not updated_lines:
        updated_window = ""
    else:
        if focus_start is not None:
            w_s = max(1, focus_start - 2)
            end_anchor = focus_end if focus_end is not None else focus_start
            w_e = min(len(updated_lines), max(w_s, end_anchor + 2))
            if w_e - w_s + 1 > 60:
                w_e = w_s + 59
        else:
            w_s = 1
            w_e = min(len(updated_lines), 60)
        updated_window = format_hashline_range(updated_lines, w_s, w_e)

    diag_ok, syntax_err, diagnostics = run_post_edit_sensors(tool_name, rel_posix, resolved, final_text, ctx)
    hint: str | None = None
    if not diag_ok:
        hint = (
            f"Edit saved, but post-edit sensor failed: {'; '.join(diagnostics)}. "
            "Fix using refreshed anchors from data.updated_window."
        )

    payload = {
        "path": rel_posix,
        "total_lines": len(updated_lines),
        "updated_window": updated_window,
        "syntax_ok": diag_ok,
        "syntax_error": syntax_err,
        "diagnostics": diagnostics,
        **extra_data,
    }
    return ok_result(payload, truncated=False, hint=hint)


def _handle_edit_search_replace(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    old_string: str = args["old_string"]
    new_string: str = args["new_string"]
    replace_all: bool = args.get("replace_all", False)

    if not old_string:
        return err_result(
            "old_string cannot be empty.",
            error_code=ERR_EDIT_APPLY,
            hint="Provide a non-empty exact snippet to replace, or use write_file on empty files.",
        )

    resolved, rel_posix, err = resolve_workspace_path(
        args["path"],
        ctx,
        check_allowed=True,
        allow_root=False,
        for_mutation=True,
    )
    if err is not None or resolved is None or rel_posix is None:
        return err  # type: ignore[return-value]

    if not resolved.exists():
        return err_result(
            f"File '{rel_posix}' does not exist.",
            error_code=ERR_NOT_FOUND,
            hint="Use write_file to create a new file or list_files() to check paths.",
        )
    if resolved.is_dir():
        return err_result(
            f"Path '{rel_posix}' is a directory, not a file.",
            error_code=ERR_INVALID_TARGET,
            hint=f"Call list_files(path={rel_posix!r}) and target a file.",
        )

    info, read_err = read_text_safe(resolved, rel_posix)
    if read_err is not None or info is None:
        return read_err  # type: ignore[return-value]

    text: str = info["text"]
    newline: str = info["newline"]
    norm_old = _normalize_to_file_newline(old_string, newline)
    norm_new = _normalize_to_file_newline(new_string, newline)

    count = text.count(norm_old)
    if count == 0:
        first_stripped = next((ln.strip() for ln in old_string.splitlines() if ln.strip()), "")
        near_lines = [
            idx for idx, ln in enumerate(info["lines"], start=1)
            if first_stripped and first_stripped in ln
        ][:5]
        near_msg = f" Similar text found near line(s) {near_lines}." if near_lines else ""
        return err_result(
            f"old_string did not match any text in '{rel_posix}'.{near_msg}",
            error_code=ERR_EDIT_APPLY,
            hint=f"Check whitespace/tabs/indentation with read_file(path={rel_posix!r}) and retry.",
        )

    if count > 1 and not replace_all:
        match_lines: list[int] = []
        pos = 0
        while True:
            found = text.find(norm_old, pos)
            if found == -1:
                break
            match_lines.append(text.count("\n", 0, found) + 1)
            pos = found + len(norm_old)
        return err_result(
            f"old_string matched {count} locations in '{rel_posix}' (lines {match_lines}) and replace_all=False.",
            error_code=ERR_EDIT_APPLY,
            hint="Include more surrounding lines to make old_string unique, or pass replace_all=True.",
        )

    first_idx = text.find(norm_old)
    focus_start = text.count("\n", 0, first_idx) + 1 if first_idx != -1 else 1
    new_line_span = max(1, len(norm_new.splitlines()))
    focus_end = focus_start + new_line_span - 1 if not replace_all else min(len(text.splitlines()) + new_line_span, focus_start + 55)

    final_text = text.replace(norm_old, norm_new) if replace_all else text.replace(norm_old, norm_new, 1)
    replacements = count if replace_all else 1
    return _save_and_sense(
        "edit_search_replace",
        resolved,
        rel_posix,
        final_text,
        ctx,
        {"replacements": replacements},
        focus_start=focus_start,
        focus_end=focus_end,
    )


def _parse_unified_diff(diff_text: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    raw_lines = diff_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    hunks: list[dict[str, Any]] = []
    idx = 0
    while idx < len(raw_lines):
        line = raw_lines[idx]
        m = _HUNK_HEADER_RE.match(line)
        if not m:
            idx += 1
            continue
        old_start = int(m.group(1))
        new_start = int(m.group(3))
        idx += 1

        ops: list[tuple[str, str]] = []
        seen_old = 0
        seen_new = 0
        no_eof_new: bool | None = None

        while idx < len(raw_lines):
            cur = raw_lines[idx]
            if _HUNK_HEADER_RE.match(cur):
                break
            if cur == r"\ No newline at end of file":
                if ops and ops[-1][0] in {"+", " "}:
                    no_eof_new = True
                idx += 1
                continue
            if not cur:
                remaining = raw_lines[idx + 1 :]
                next_nonempty = next((ln for ln in remaining if ln), None)
                if idx == len(raw_lines) - 1 or next_nonempty is None or _HUNK_HEADER_RE.match(next_nonempty):
                    idx += 1
                    break
                # Model-generated hunks sometimes omit the leading space on blank context lines
                ops.append((" ", ""))
                seen_old += 1
                seen_new += 1
                idx += 1
                continue
            prefix = cur[0]
            if prefix not in {" ", "+", "-"}:
                return None, f"Invalid unified diff line prefix {prefix!r} at hunk line {idx + 1}"
            body = cur[1:]
            ops.append((prefix, body))
            if prefix in {" ", "-"}:
                seen_old += 1
            if prefix in {" ", "+"}:
                seen_new += 1
            idx += 1

        if not ops:
            return None, f"Unified diff hunk at line {idx + 1} contains no diff lines"

        hunks.append({
            "old_start": old_start,
            "old_count": seen_old,
            "new_start": new_start,
            "new_count": seen_new,
            "ops": ops,
            "no_eof_new": no_eof_new,
        })

    if not hunks:
        return None, "No valid @@ unified diff hunk headers found"
    return hunks, None


def _handle_edit_unified_diff(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    diff_text: str = args["diff"]
    hunks, parse_err = _parse_unified_diff(diff_text)
    if parse_err or hunks is None:
        return err_result(
            f"Malformed unified diff: {parse_err}.",
            error_code=ERR_EDIT_APPLY,
            hint="Provide valid unified diff hunks starting with '@@ -old_start,old_count +new_start,new_count @@'.",
        )

    resolved, rel_posix, err = resolve_workspace_path(
        args["path"],
        ctx,
        check_allowed=True,
        allow_root=False,
        for_mutation=True,
    )
    if err is not None or resolved is None or rel_posix is None:
        return err  # type: ignore[return-value]

    if not resolved.exists():
        return err_result(
            f"File '{rel_posix}' does not exist.",
            error_code=ERR_NOT_FOUND,
            hint="Use write_file to create a new file before patching.",
        )
    if resolved.is_dir():
        return err_result(
            f"Path '{rel_posix}' is a directory, not a file.",
            error_code=ERR_INVALID_TARGET,
            hint=f"Call list_files(path={rel_posix!r}) and target a file.",
        )

    info, read_err = read_text_safe(resolved, rel_posix)
    if read_err is not None or info is None:
        return read_err  # type: ignore[return-value]

    current_lines: list[str] = list(info["lines"])
    newline: str = info["newline"]
    has_trailing_newline: bool = True if len(current_lines) == 0 else info["has_trailing_newline"]
    delta = 0
    min_search_idx = 0
    first_focus_start: int | None = None
    last_focus_end: int | None = None

    for hunk_idx, hunk in enumerate(hunks, start=1):
        old_chunk = [body for op, body in hunk["ops"] if op in {" ", "-"}]
        new_chunk = [body for op, body in hunk["ops"] if op in {" ", "+"}]
        old_start: int = hunk["old_start"]

        if not old_chunk:
            insert_at = min_search_idx if old_start == 0 else max(
                min_search_idx,
                min(len(current_lines), old_start + delta),
            )
            current_lines = current_lines[:insert_at] + new_chunk + current_lines[insert_at:]
            if first_focus_start is None:
                first_focus_start = insert_at + 1
            last_focus_end = insert_at + max(1, len(new_chunk))
            min_search_idx = insert_at + len(new_chunk)
            delta += len(new_chunk)
        else:
            expected_idx = max(min_search_idx, old_start - 1 + delta)
            span = len(old_chunk)
            if (
                expected_idx + span <= len(current_lines)
                and current_lines[expected_idx : expected_idx + span] == old_chunk
            ):
                match_idx = expected_idx
            else:
                candidates = [
                    j for j in range(min_search_idx, len(current_lines) - span + 1)
                    if current_lines[j : j + span] == old_chunk
                ]
                if len(candidates) == 1:
                    match_idx = candidates[0]
                    delta = match_idx - (old_start - 1)
                elif len(candidates) > 1:
                    lines_1based = [c + 1 for c in candidates[:5]]
                    return err_result(
                        f"Unified diff hunk #{hunk_idx} is ambiguous (matches lines {lines_1based}) in '{rel_posix}'.",
                        error_code=ERR_EDIT_APPLY,
                        hint="Include more context lines in the hunk so it matches uniquely.",
                    )
                else:
                    return err_result(
                        f"Unified diff hunk #{hunk_idx} failed to match context around line {old_start} in '{rel_posix}'.",
                        error_code=ERR_EDIT_APPLY,
                        hint=f"Read '{rel_posix}' with read_file() and regenerate the diff against current lines.",
                    )
            current_lines = current_lines[:match_idx] + new_chunk + current_lines[match_idx + span :]
            if first_focus_start is None:
                first_focus_start = match_idx + 1
            last_focus_end = match_idx + max(1, len(new_chunk))
            min_search_idx = match_idx + len(new_chunk)
            delta += len(new_chunk) - span

        if hunk.get("no_eof_new") is True:
            has_trailing_newline = False

    if not current_lines:
        final_text = ""
    else:
        final_text = newline.join(current_lines) + (newline if has_trailing_newline else "")

    return _save_and_sense(
        "edit_unified_diff",
        resolved,
        rel_posix,
        final_text,
        ctx,
        {"hunks_applied": len(hunks)},
        focus_start=first_focus_start,
        focus_end=last_focus_end,
    )


def _handle_edit_line_range(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    start_line: int = args["start_line"]
    end_line: int = args["end_line"]
    new_content: str = args.get("new_content", "")
    delete_lines: bool = args.get("delete_lines", False)

    resolved, rel_posix, err = resolve_workspace_path(
        args["path"],
        ctx,
        check_allowed=True,
        allow_root=False,
        for_mutation=True,
    )
    if err is not None or resolved is None or rel_posix is None:
        return err  # type: ignore[return-value]

    if not resolved.exists():
        return err_result(
            f"File '{rel_posix}' does not exist.",
            error_code=ERR_NOT_FOUND,
            hint="Use write_file to create a new file.",
        )
    if resolved.is_dir():
        return err_result(
            f"Path '{rel_posix}' is a directory, not a file.",
            error_code=ERR_INVALID_TARGET,
            hint=f"Call list_files(path={rel_posix!r}) and target a file.",
        )

    info, read_err = read_text_safe(resolved, rel_posix)
    if read_err is not None or info is None:
        return read_err  # type: ignore[return-value]

    lines: list[str] = list(info["lines"])
    total_lines = len(lines)
    newline: str = info["newline"]
    has_trailing_newline: bool = info["has_trailing_newline"]

    if start_line == 0:
        if end_line != 0 or delete_lines:
            return err_result(
                "start_line=0 requires end_line=0 and delete_lines=False (top/empty-file insertion).",
                error_code=ERR_EDIT_APPLY,
                hint="Pass start_line=0, end_line=0 to prepend lines or populate an empty file.",
            )
        new_lines = _split_replacement_lines(new_content)
        updated_lines = new_lines + lines
        focus_start = 1
        focus_end = max(1, len(new_lines))
    else:
        if total_lines == 0:
            return err_result(
                f"File '{rel_posix}' is empty (0 lines); use start_line=0, end_line=0 to populate it.",
                error_code=ERR_EDIT_APPLY,
                hint="Call edit_line_range with start_line=0, end_line=0.",
            )
        if end_line < start_line or start_line > total_lines or end_line > total_lines:
            return err_result(
                f"Line range {start_line}-{end_line} is invalid for '{rel_posix}' ({total_lines} lines).",
                error_code=ERR_EDIT_APPLY,
                hint=f"Read valid 1-based line numbers (1..{total_lines}) with read_file().",
            )
        if delete_lines:
            updated_lines = lines[: start_line - 1] + lines[end_line:]
            if updated_lines:
                focus_start = max(1, min(len(updated_lines), start_line - 1))
                focus_end = min(len(updated_lines), focus_start + 2)
            else:
                focus_start = 0
                focus_end = 0
        else:
            new_lines = _split_replacement_lines(new_content)
            updated_lines = lines[: start_line - 1] + new_lines + lines[end_line:]
            focus_start = start_line
            focus_end = start_line + max(0, len(new_lines) - 1)

    if not updated_lines:
        final_text = ""
    else:
        final_text = newline.join(updated_lines) + (newline if has_trailing_newline else "")

    return _save_and_sense(
        "edit_line_range",
        resolved,
        rel_posix,
        final_text,
        ctx,
        {"start_line": start_line, "end_line": end_line, "deleted": delete_lines},
        focus_start=focus_start if updated_lines else None,
        focus_end=focus_end if updated_lines else None,
    )


EDIT_SEARCH_REPLACE_SPEC = ToolSpec(
    name="edit_search_replace",
    description="Replace an exact string block in an existing file with atomic save and post-edit diagnostics.",
    effect="write",
    model_tier="slm_safe",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path to the file."},
            "old_string": {"type": "string", "description": "Exact existing text to replace."},
            "new_string": {"type": "string", "description": "Replacement text."},
            "replace_all": {
                "type": "boolean",
                "default": False,
                "description": "Replace all matches if true; require unique match if false (default).",
            },
        },
        "required": ["path", "old_string", "new_string"],
        "additionalProperties": False,
    },
    handler=_handle_edit_search_replace,
)

EDIT_UNIFIED_DIFF_SPEC = ToolSpec(
    name="edit_unified_diff",
    description="Apply a unified diff patch (@@ hunks) to an existing file atomically with post-edit diagnostics.",
    effect="write",
    model_tier="slm_safe",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path to the file."},
            "diff": {"type": "string", "description": "Unified diff patch text containing one or more @@ hunks."},
        },
        "required": ["path", "diff"],
        "additionalProperties": False,
    },
    handler=_handle_edit_unified_diff,
)

EDIT_LINE_RANGE_SPEC = ToolSpec(
    name="edit_line_range",
    description="Replace or delete an inclusive 1-based line range (or pass 0,0 to insert at file top/empty file).",
    effect="write",
    model_tier="slm_safe",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path to the file."},
            "start_line": {
                "type": "integer",
                "minimum": 0,
                "description": "1-based start line, or 0 (with end_line=0) to insert at start/empty file.",
            },
            "end_line": {
                "type": "integer",
                "minimum": 0,
                "description": "1-based inclusive end line, or 0 when start_line=0.",
            },
            "new_content": {
                "type": "string",
                "default": "",
                "description": "Replacement or inserted lines (ignored when delete_lines=True).",
            },
            "delete_lines": {
                "type": "boolean",
                "default": False,
                "description": "Set true to delete lines start_line..end_line instead of replacing.",
            },
        },
        "required": ["path", "start_line", "end_line"],
        "additionalProperties": False,
    },
    handler=_handle_edit_line_range,
)

EDIT_STRATEGY_SPECS: Mapping[str, ToolSpec] = {
    "hashline": EDIT_FILE_SPEC,
    "search_and_replace": EDIT_SEARCH_REPLACE_SPEC,
    "unified_diff": EDIT_UNIFIED_DIFF_SPEC,
    "line_range_patch": EDIT_LINE_RANGE_SPEC,
    "whole_file_rewrite": WRITE_FILE_SPEC,
}
