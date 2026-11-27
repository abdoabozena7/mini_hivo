"""Structural code intelligence tool unit: ``code_intel``."""

from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import Any

from .base import (
    ERR_INVALID_TARGET,
    ERR_NOT_FOUND,
    ERR_TOOL_SCHEMA,
    ToolContext,
    ToolSpec,
    err_result,
    is_secret_path,
    line_hash,
    ok_result,
    read_text_safe,
    resolve_workspace_path,
)
from .fs_read import _iter_searchable_files

_CODE_SUFFIXES: frozenset[str] = frozenset({
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".cc",
    ".h",
    ".hpp",
})

_REGEX_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("class", re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)")),
    ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_][A-Za-z0-9_]*)")),
    ("type", re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_][A-Za-z0-9_]*)\s*=")),
    ("struct", re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_][A-Za-z0-9_]*)")),
    ("function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")),
    ("function", re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s+)?\(?[^=]*\)?\s*=>")),
    ("function", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")),
    ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(")),
)


def _make_anchor(lines: list[str], line_no: int) -> str:
    txt = lines[line_no - 1] if 1 <= line_no <= len(lines) else ""
    return f"{line_no}:{line_hash(txt)}"


def _format_py_args(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    names: list[str] = [a.arg for a in fn_node.args.posonlyargs]
    names.extend(a.arg for a in fn_node.args.args)
    if fn_node.args.vararg is not None:
        names.append("*" + fn_node.args.vararg.arg)
    names.extend(a.arg for a in fn_node.args.kwonlyargs)
    if fn_node.args.kwarg is not None:
        names.append("**" + fn_node.args.kwarg.arg)
    joined = ", ".join(names)
    return joined[:77] + "..." if len(joined) > 80 else joined


def _extract_python_symbols(lines: list[str], source: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _extract_regex_symbols(lines)

    symbols: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            start = node.lineno
            end = node.end_lineno or start
            symbols.append({
                "name": node.name,
                "kind": "class",
                "signature": f"class {node.name}",
                "start_line": start,
                "end_line": end,
                "anchor": _make_anchor(lines, start),
                "end_anchor": _make_anchor(lines, end),
            })
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    c_start = child.lineno
                    c_end = child.end_lineno or c_start
                    prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                    symbols.append({
                        "name": f"{node.name}.{child.name}",
                        "kind": "method",
                        "signature": f"{prefix} {child.name}({_format_py_args(child)})",
                        "start_line": c_start,
                        "end_line": c_end,
                        "anchor": _make_anchor(lines, c_start),
                        "end_anchor": _make_anchor(lines, c_end),
                    })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = node.end_lineno or start
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            symbols.append({
                "name": node.name,
                "kind": "function",
                "signature": f"{prefix} {node.name}({_format_py_args(node)})",
                "start_line": start,
                "end_line": end,
                "anchor": _make_anchor(lines, start),
                "end_anchor": _make_anchor(lines, end),
            })
        elif isinstance(node, ast.Assign):
            start = node.lineno
            end = node.end_lineno or start
            raw_sig = lines[start - 1].strip() if 1 <= start <= len(lines) else ""
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    sig = raw_sig or tgt.id
                    if len(sig) > 100:
                        sig = sig[:97] + "..."
                    symbols.append({
                        "name": tgt.id,
                        "kind": "variable",
                        "signature": sig,
                        "start_line": start,
                        "end_line": end,
                        "anchor": _make_anchor(lines, start),
                        "end_anchor": _make_anchor(lines, end),
                    })
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            start = node.lineno
            end = node.end_lineno or start
            raw_sig = lines[start - 1].strip() if 1 <= start <= len(lines) else node.target.id
            sig = raw_sig[:97] + "..." if len(raw_sig) > 100 else raw_sig
            symbols.append({
                "name": node.target.id,
                "kind": "variable",
                "signature": sig,
                "start_line": start,
                "end_line": end,
                "anchor": _make_anchor(lines, start),
                "end_anchor": _make_anchor(lines, end),
            })
    return symbols


def _strip_comments_and_strings(line: str, in_block_comment: bool) -> tuple[str, bool]:
    """Return code-only characters from ``line`` (for brace/paren counting) and updated block comment state."""
    out: list[str] = []
    i = 0
    n = len(line)
    in_quote: str | None = None
    while i < n:
        ch = line[i]
        nxt = line[i + 1] if i + 1 < n else ""
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue
        if in_quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
            i += 1
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if (ch == "/" and nxt == "/") or ch == "#":
            break
        if ch in {'"', "'", "`"}:
            in_quote = ch
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), in_block_comment


def _find_brace_block_end(lines: list[str], start_idx: int) -> int:
    start_line = start_idx + 1
    if re.match(r"^\s*(?:async\s+)?def\b", lines[start_idx]):
        return start_line

    brace_depth = 0
    paren_depth = 0
    seen_open = False
    in_block_comment = False

    for k in range(start_idx, len(lines)):
        code, in_block_comment = _strip_comments_and_strings(lines[k], in_block_comment)
        for ch in code:
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth = max(0, paren_depth - 1)
            elif ch == "{":
                brace_depth += 1
                seen_open = True
            elif ch == "}":
                if seen_open:
                    brace_depth -= 1
                    if brace_depth <= 0:
                        return k + 1
        if not seen_open:
            stripped = code.strip()
            if stripped.endswith(";") and paren_depth == 0:
                return start_line
            if stripped.endswith(":") and not stripped.endswith("::") and paren_depth == 0:
                nxt = next((ln.lstrip() for ln in lines[k + 1 : k + 5] if ln.strip()), "")
                if not nxt.startswith("{"):
                    return start_line
            if k - start_idx >= 8:
                return start_line
    return start_line


def _extract_regex_symbols(lines: list[str]) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        for kind, pat in _REGEX_PATTERNS:
            m = pat.match(line)
            if m:
                sym_name = m.group(1)
                sig = line.strip().rstrip("{").strip()
                if len(sig) > 100:
                    sig = sig[:97] + "..."
                end_line = _find_brace_block_end(lines, idx - 1)
                symbols.append({
                    "name": sym_name,
                    "kind": kind,
                    "signature": sig,
                    "start_line": idx,
                    "end_line": end_line,
                    "anchor": _make_anchor(lines, idx),
                    "end_anchor": _make_anchor(lines, end_line),
                })
                break
    return symbols


def _extract_symbols_for_file(file_path: Path, rel_posix: str) -> tuple[list[dict[str, Any]], int] | None:
    if file_path.suffix.casefold() not in _CODE_SUFFIXES:
        return None
    info, err = read_text_safe(file_path, rel_posix)
    if err is not None or info is None:
        return None
    lines: list[str] = info["lines"]
    source: str = info["text"]
    if file_path.suffix.casefold() in {".py", ".pyi"}:
        syms = _extract_python_symbols(lines, source)
    else:
        syms = _extract_regex_symbols(lines)
    return syms, len(lines)


def _handle_code_intel(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    action: str = args["action"]
    symbol: str = (args.get("symbol", "") or "").strip()

    if action in {"find_symbol", "find_references"} and not symbol:
        return err_result(
            f"Parameter 'symbol' is required for code_intel action '{action}'.",
            error_code=ERR_TOOL_SCHEMA,
            hint=f"Pass a non-empty 'symbol' name when calling code_intel(action={action!r}).",
        )

    if action == "outline":
        resolved, rel_posix, err = resolve_workspace_path(
            args.get("path", "."),
            ctx,
            check_allowed=True,
            allow_root=False,
        )
        if err is not None or resolved is None or rel_posix is None:
            return err  # type: ignore[return-value]
        if not resolved.exists():
            return err_result(
                f"File '{rel_posix}' does not exist.",
                error_code=ERR_NOT_FOUND,
                hint="Call list_files() to check available files.",
            )
        if resolved.is_dir():
            return err_result(
                f"Path '{rel_posix}' is a directory; action='outline' requires a file path.",
                error_code=ERR_INVALID_TARGET,
                hint=f"Pass action='repo_map' for directory outlines or specify a file inside '{rel_posix}'.",
            )
        info, read_err = read_text_safe(resolved, rel_posix)
        if read_err is not None or info is None:
            return read_err  # type: ignore[return-value]
        lines = info["lines"]
        if resolved.suffix.casefold() in {".py", ".pyi"}:
            syms = _extract_python_symbols(lines, info["text"])
        else:
            syms = _extract_regex_symbols(lines)
        return ok_result({
            "action": "outline",
            "path": rel_posix,
            "total_lines": len(lines),
            "symbol_count": len(syms),
            "symbols": syms,
        })

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
            f"Path '{rel_posix}' does not exist.",
            error_code=ERR_NOT_FOUND,
            hint="Call list_files(path='.') to inspect valid workspace paths.",
        )

    files = _iter_searchable_files(resolved, ctx, file_glob="")
    files = [(fp, rp) for fp, rp in files if fp.suffix.casefold() in _CODE_SUFFIXES and not (ctx.block_secret_files and is_secret_path(rp))]

    if action == "repo_map":
        max_entries = max(1, ctx.max_list_entries)
        max_chars = max(256, ctx.max_output_chars)
        entries: list[dict[str, Any]] = []
        used_chars = 0
        truncated = False
        total_files = len(files)

        for fp, rp in files:
            extracted = _extract_symbols_for_file(fp, rp)
            if extracted is None:
                continue
            syms, total_lines = extracted
            compact_syms = [
                {
                    "name": s["name"],
                    "kind": s["kind"],
                    "start_line": s["start_line"],
                    "end_line": s["end_line"],
                }
                for s in syms
            ]
            item = {"path": rp, "total_lines": total_lines, "symbols": compact_syms}
            est = len(rp) + sum(len(s["name"]) + 24 for s in compact_syms) + 32
            if len(entries) >= max_entries or (entries and used_chars + est > max_chars):
                truncated = True
                break
            entries.append(item)
            used_chars += est

        hint = (
            f"Showing {len(entries)} of {total_files} source files. Pass a narrower 'path' to inspect specific subtrees."
            if truncated else None
        )
        return ok_result(
            {
                "action": "repo_map",
                "path": rel_posix,
                "files": entries,
                "file_count": len(entries),
                "total_files": total_files,
            },
            truncated=truncated,
            hint=hint,
        )

    if action == "find_symbol":
        exact: list[dict[str, Any]] = []
        fuzzy: list[dict[str, Any]] = []
        sym_cf = symbol.casefold()
        for fp, rp in files:
            extracted = _extract_symbols_for_file(fp, rp)
            if extracted is None:
                continue
            syms, _ = extracted
            for s in syms:
                short_name = s["name"].split(".")[-1]
                entry = {"path": rp, **s}
                if s["name"] == symbol or short_name == symbol:
                    exact.append(entry)
                elif sym_cf in s["name"].casefold():
                    fuzzy.append(entry)

        all_matches = exact if exact else fuzzy
        cap = max(1, ctx.max_search_matches)
        truncated = len(all_matches) > cap
        shown = all_matches[:cap]
        hint = (
            f"Showing {len(shown)} of {len(all_matches)} symbol matches. Pass a narrower 'path' to refine."
            if truncated else None
        )
        return ok_result(
            {
                "action": "find_symbol",
                "symbol": symbol,
                "matches": shown,
                "match_count": len(shown),
                "total_matches": len(all_matches),
            },
            truncated=truncated,
            hint=hint,
        )

    # find_references
    ref_re = re.compile(rf"\b{re.escape(symbol)}\b")
    cap = max(1, ctx.max_search_matches)
    matches: list[dict[str, Any]] = []
    total_matches = 0
    truncated = False

    for fp, rp in files:
        info, read_err = read_text_safe(fp, rp)
        if read_err is not None or info is None:
            continue
        lines = info["lines"]
        if fp.suffix.casefold() in {".py", ".pyi"}:
            syms = _extract_python_symbols(lines, info["text"])
        else:
            syms = _extract_regex_symbols(lines)
        def_lines = {
            s["start_line"] for s in syms
            if s["name"] == symbol or s["name"].split(".")[-1] == symbol
        }
        for idx, line in enumerate(lines, start=1):
            if ref_re.search(line):
                total_matches += 1
                if len(matches) < cap:
                    clipped = line.strip()
                    if len(clipped) > 200:
                        clipped = clipped[:197] + "..."
                    matches.append({
                        "path": rp,
                        "line": idx,
                        "anchor": f"{idx}:{line_hash(line)}",
                        "is_definition": idx in def_lines,
                        "text": clipped,
                    })
                else:
                    truncated = True

    hint = (
        f"Showing {len(matches)} of {total_matches} references. Narrow 'path' to focus on one module."
        if truncated else None
    )
    return ok_result(
        {
            "action": "find_references",
            "symbol": symbol,
            "matches": matches,
            "match_count": len(matches),
            "total_matches": total_matches,
        },
        truncated=truncated,
        hint=hint,
    )


CODE_INTEL_SPEC = ToolSpec(
    name="code_intel",
    description=(
        "Structural AST/symbol navigation without reading full file bodies: inspect file 'outline', "
        "build a compact 'repo_map', jump to definitions via 'find_symbol', or list 'find_references'."
    ),
    effect="read",
    model_tier="slm_safe",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["repo_map", "outline", "find_symbol", "find_references"],
                "description": "Structural navigation query to execute.",
            },
            "path": {
                "type": "string",
                "default": ".",
                "description": "Workspace-relative file (for outline) or directory (for repo_map/search).",
            },
            "symbol": {
                "type": "string",
                "default": "",
                "description": "Symbol name required for find_symbol and find_references.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    },
    handler=_handle_code_intel,
)
