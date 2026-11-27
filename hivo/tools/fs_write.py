"""Atomic file mutation tool units: ``edit_file`` (Hashlines), ``write_file``, ``delete_file``."""

from __future__ import annotations

import re
from typing import Any

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
    line_hash,
    maybe_backup,
    ok_result,
    parse_anchor,
    read_text_safe,
    resolve_workspace_path,
)
from .hooks import run_post_edit_sensors


def _split_replacement_lines(content: str) -> list[str]:
    norm = content.replace("\r\n", "\n").replace("\r", "\n")
    if norm == "":
        return [""]
    if norm.endswith("\n"):
        norm = norm[:-1]
    return norm.split("\n")


def _handle_edit_file(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    operation: str = args["operation"]
    start_anchor_raw: str = args["start_anchor"]
    end_anchor_raw: str = args.get("end_anchor", "") or ""
    has_content = "content" in args and args["content"] is not None

    if operation in {"replace", "insert_after"} and not has_content:
        return err_result(
            f"Missing 'content' parameter for edit_file operation '{operation}'.",
            error_code=ERR_EDIT_APPLY,
            hint="Provide a 'content' string for 'replace' or 'insert_after', or use operation='delete'.",
        )
    if operation == "delete" and has_content and args["content"] != "":
        return err_result(
            "Parameter 'content' must not be provided when operation='delete'.",
            error_code=ERR_EDIT_APPLY,
            hint="Omit 'content' for operation='delete', or use operation='replace' to substitute text.",
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
            hint=f"Call write_file(path={rel_posix!r}, content=...) to create a new file, or list_files() to check paths.",
        )
    if resolved.is_dir():
        return err_result(
            f"Path '{rel_posix}' is a directory, not a file.",
            error_code=ERR_INVALID_TARGET,
            hint=f"Call list_files(path={rel_posix!r}) and target a specific file.",
        )

    info, read_err = read_text_safe(resolved, rel_posix)
    if read_err is not None or info is None:
        return read_err  # type: ignore[return-value]

    lines: list[str] = list(info["lines"])
    total_lines = len(lines)
    newline: str = info["newline"]
    has_trailing_newline: bool = info["has_trailing_newline"]

    is_top_anchor = start_anchor_raw.strip() == "0:00"
    if is_top_anchor:
        if operation != "insert_after":
            return err_result(
                "Anchor '0:00' can only be used with operation='insert_after'.",
                error_code=ERR_EDIT_APPLY,
                hint=(
                    "Use operation='insert_after' with start_anchor='0:00' to insert at the top/empty file, "
                    "or read real line anchors with read_file()."
                ),
            )
        if end_anchor_raw.strip() not in {"", "0:00"}:
            return err_result(
                "end_anchor must be empty or '0:00' when start_anchor is '0:00'.",
                error_code=ERR_EDIT_APPLY,
                hint="Omit 'end_anchor' when inserting at '0:00'.",
            )
        new_lines = _split_replacement_lines(args["content"])
        updated_lines = new_lines + lines
        window_start = 1
        window_end = len(new_lines)
    else:
        if total_lines == 0:
            return err_result(
                f"File '{rel_posix}' is empty (0 lines), so anchor '{start_anchor_raw}' cannot match.",
                error_code=ERR_EDIT_APPLY,
                hint=f"Use edit_file(path={rel_posix!r}, operation='insert_after', start_anchor='0:00', content=...) or write_file(overwrite=True).",
            )

        parsed_start = parse_anchor(start_anchor_raw)
        if parsed_start is None:
            return err_result(
                f"Malformed start_anchor {start_anchor_raw!r}.",
                error_code=ERR_EDIT_APPLY,
                hint=f"Anchors must look like '42:a3'. Call read_file(path={rel_posix!r}) to get valid anchors.",
            )
        start_line, start_hash = parsed_start

        effective_end_raw = end_anchor_raw.strip() or start_anchor_raw
        parsed_end = parse_anchor(effective_end_raw)
        if parsed_end is None:
            return err_result(
                f"Malformed end_anchor {end_anchor_raw!r}.",
                error_code=ERR_EDIT_APPLY,
                hint=f"Anchors must look like '47:f1'. Call read_file(path={rel_posix!r}) to get valid anchors.",
            )
        end_line, end_hash = parsed_end

        if operation == "insert_after" and (end_line != start_line or end_hash != start_hash):
            return err_result(
                "operation='insert_after' targets a single anchor line; end_anchor cannot differ from start_anchor.",
                error_code=ERR_EDIT_APPLY,
                hint="Omit 'end_anchor' when calling edit_file with operation='insert_after'.",
            )

        if start_line < 1 or start_line > total_lines or end_line < start_line or end_line > total_lines:
            return err_result(
                f"Anchor line range {start_line}-{end_line} is out of bounds for '{rel_posix}' ({total_lines} lines).",
                error_code=ERR_EDIT_APPLY,
                hint=f"Call read_file(path={rel_posix!r}, start_line=1, end_line={min(total_lines, ctx.max_read_lines)}) for current anchors.",
            )

        actual_start_hash = line_hash(lines[start_line - 1])
        actual_end_hash = line_hash(lines[end_line - 1])
        mismatches: list[str] = []
        if actual_start_hash != start_hash:
            mismatches.append(f"line {start_line} (expected {start_hash}, found {actual_start_hash})")
        if end_line != start_line and actual_end_hash != end_hash:
            mismatches.append(f"line {end_line} (expected {end_hash}, found {actual_end_hash})")
        elif end_line == start_line and actual_end_hash != end_hash and actual_start_hash == start_hash:
            mismatches.append(f"line {end_line} (expected {end_hash}, found {actual_end_hash})")

        if mismatches:
            win_s = max(1, start_line - 3)
            win_e = min(total_lines, end_line + 3)
            current_window = format_hashline_range(lines, win_s, win_e)
            return err_result(
                f"Hash mismatch in '{rel_posix}' at {', '.join(mismatches)}. File was not modified.",
                error_code=ERR_EDIT_APPLY,
                data={
                    "path": rel_posix,
                    "total_lines": total_lines,
                    "current_window": current_window,
                },
                hint=(
                    f"Use the refreshed Hashline anchors from data.current_window, or call "
                    f"read_file(path={rel_posix!r}, start_line={win_s}, end_line={win_e}) before retrying."
                ),
            )

        if operation == "replace":
            new_lines = _split_replacement_lines(args["content"])
            updated_lines = lines[: start_line - 1] + new_lines + lines[end_line:]
            window_start = start_line
            window_end = start_line + len(new_lines) - 1
        elif operation == "insert_after":
            new_lines = _split_replacement_lines(args["content"])
            updated_lines = lines[:start_line] + new_lines + lines[start_line:]
            window_start = start_line + 1
            window_end = start_line + len(new_lines)
        else:  # delete
            updated_lines = lines[: start_line - 1] + lines[end_line:]
            if updated_lines:
                window_start = max(1, min(len(updated_lines), start_line - 1))
                window_end = min(len(updated_lines), window_start + 2)
            else:
                window_start = 0
                window_end = 0

    if not updated_lines:
        final_text = ""
    else:
        final_text = newline.join(updated_lines) + (newline if has_trailing_newline else "")

    try:
        maybe_backup(resolved, rel_posix, ctx)
        atomic_write_bytes(resolved, final_text.encode("utf-8"))
    except OSError as exc:
        return err_result(
            f"Failed to write '{rel_posix}': {exc}.",
            error_code=ERR_INFRA,
            hint="Verify workspace permissions and retry.",
        )

    if not updated_lines:
        updated_window = ""
    else:
        w_s = max(1, window_start - 2)
        w_e = min(len(updated_lines), window_end + 2)
        if w_e - w_s + 1 > 60:
            w_e = w_s + 59
        updated_window = format_hashline_range(updated_lines, w_s, w_e)

    diag_ok, syntax_err, diagnostics = run_post_edit_sensors("edit_file", rel_posix, resolved, final_text, ctx)
    hint: str | None = None
    if not diag_ok:
        hint = (
            f"Edit saved, but post-edit sensor failed: {'; '.join(diagnostics)}. "
            "Fix using edit_file with refreshed anchors from data.updated_window."
        )

    return ok_result(
        {
            "path": rel_posix,
            "operation": operation,
            "total_lines": len(updated_lines),
            "updated_window": updated_window,
            "syntax_ok": diag_ok,
            "syntax_error": syntax_err,
            "diagnostics": diagnostics,
        },
        truncated=False,
        hint=hint,
    )


def _handle_write_file(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    resolved, rel_posix, err = resolve_workspace_path(
        args["path"],
        ctx,
        check_allowed=True,
        allow_root=False,
        for_mutation=True,
    )
    if err is not None or resolved is None or rel_posix is None:
        return err  # type: ignore[return-value]

    if resolved.exists() and resolved.is_dir():
        return err_result(
            f"Path '{rel_posix}' is an existing directory, not a file.",
            error_code=ERR_INVALID_TARGET,
            hint="Pass a file path inside the directory.",
        )

    existed = resolved.exists()
    overwrite: bool = args.get("overwrite", False)
    if existed and not overwrite:
        return err_result(
            f"File '{rel_posix}' already exists and overwrite=False.",
            error_code=ERR_EDIT_APPLY,
            hint=(
                f"Call edit_file(path={rel_posix!r}, ...) for targeted edits, "
                f"or pass overwrite=True to replace the entire file."
            ),
        )

    text_to_write: str = args["content"]
    if existed and resolved.is_file():
        try:
            prev_raw = resolved.read_bytes()
        except OSError:
            prev_raw = b""
        if prev_raw and b"\x00" not in prev_raw[:8192]:
            crlf_count = prev_raw.count(b"\r\n")
            lf_only = prev_raw.count(b"\n") - crlf_count
            if crlf_count > 0 and crlf_count >= lf_only and "\r\n" not in text_to_write:
                text_to_write = text_to_write.replace("\r", "").replace("\n", "\r\n")

    raw_bytes = text_to_write.encode("utf-8")

    try:
        if existed:
            maybe_backup(resolved, rel_posix, ctx)
        atomic_write_bytes(resolved, raw_bytes)
    except OSError as exc:
        return err_result(
            f"Failed to write '{rel_posix}': {exc}.",
            error_code=ERR_INFRA,
            hint="Verify workspace permissions and path validity.",
        )

    diag_ok, syntax_err, diagnostics = run_post_edit_sensors("write_file", rel_posix, resolved, text_to_write, ctx)
    written_lines = text_to_write.splitlines()
    if not written_lines:
        updated_window = ""
    else:
        err_line: int | None = None
        if syntax_err:
            m = re.search(r"\bline\s+(\d+)\b", syntax_err) or re.search(r":(\d+)\b", syntax_err)
            if m:
                err_line = int(m.group(1))
        if err_line is not None:
            center = max(1, min(len(written_lines), err_line))
            w_s = max(1, center - 19)
            w_e = min(len(written_lines), w_s + 39)
            if w_e == len(written_lines):
                w_s = max(1, w_e - 39)
        else:
            w_s = 1
            w_e = min(len(written_lines), 40)
        updated_window = format_hashline_range(written_lines, w_s, w_e)

    hint: str | None = None
    if not diag_ok:
        hint = (
            f"File written, but post-edit sensor failed: {'; '.join(diagnostics)}. "
            "Fix using edit_file with refreshed anchors from data.updated_window."
        )

    return ok_result(
        {
            "path": rel_posix,
            "created": not existed,
            "line_count": len(written_lines),
            "byte_size": len(raw_bytes),
            "updated_window": updated_window,
            "syntax_ok": diag_ok,
            "syntax_error": syntax_err,
            "diagnostics": diagnostics,
        },
        truncated=False,
        hint=hint,
    )


def _handle_delete_file(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
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
            hint="Call list_files() to check existing workspace files.",
        )
    if resolved.is_dir():
        return err_result(
            f"Cannot delete directory '{rel_posix}'; delete_file only removes single files.",
            error_code=ERR_INVALID_TARGET,
            hint="Pass the path of a single regular file to delete_file.",
        )

    try:
        maybe_backup(resolved, rel_posix, ctx)
        resolved.unlink()
    except OSError as exc:
        return err_result(
            f"Failed to delete '{rel_posix}': {exc}.",
            error_code=ERR_INFRA,
            hint="Verify file permissions and retry.",
        )

    return ok_result({"path": rel_posix, "deleted": True})


EDIT_FILE_SPEC = ToolSpec(
    name="edit_file",
    description=(
        "Edit an existing file using Hashline anchors ('line:hash') obtained from read_file. "
        "Validates line hashes before writing and returns refreshed anchors plus post-edit diagnostics."
    ),
    effect="write",
    model_tier="slm_safe",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path to the file."},
            "operation": {
                "type": "string",
                "enum": ["replace", "insert_after", "delete"],
                "description": "Edit operation to apply.",
            },
            "start_anchor": {
                "type": "string",
                "description": "Start line anchor ('line:hash', e.g. '42:a3'). Use '0:00' only for insert_after at file start.",
            },
            "end_anchor": {
                "type": "string",
                "default": "",
                "description": "Optional inclusive end line anchor ('line:hash'). Defaults to start_anchor.",
            },
            "content": {
                "type": "string",
                "description": "Replacement or inserted text (required for replace and insert_after; omit for delete).",
            },
        },
        "required": ["path", "operation", "start_anchor"],
        "additionalProperties": False,
    },
    handler=_handle_edit_file,
)

WRITE_FILE_SPEC = ToolSpec(
    name="write_file",
    description="Create a new file or replace an existing file when overwrite=True.",
    effect="write",
    model_tier="slm_safe",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path to the file."},
            "content": {"type": "string", "description": "Full UTF-8 text content to write."},
            "overwrite": {
                "type": "boolean",
                "default": False,
                "description": "Set true to overwrite an existing file (default false).",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    handler=_handle_write_file,
)

DELETE_FILE_SPEC = ToolSpec(
    name="delete_file",
    description="Delete a single existing file inside the workspace (directories are refused).",
    effect="write",
    model_tier="slm_safe",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path to the file to delete."},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    handler=_handle_delete_file,
)
