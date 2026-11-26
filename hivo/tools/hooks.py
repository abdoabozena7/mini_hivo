"""Tool lifecycle hook registry and instant post-edit static sensors."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, Callable

from .base import (
    ERR_HOOK_BLOCKED,
    ToolContext,
    check_syntax,
    err_result,
)

PreToolHook = Callable[[str, dict[str, Any], ToolContext], dict[str, Any] | None]
PostEditHook = Callable[[str, str, Path, ToolContext], list[str]]


class HookRegistry:
    """Deterministic lifecycle hook callbacks for tool execution and post-edit checks."""

    def __init__(self) -> None:
        self._pre_tool: list[PreToolHook] = []
        self._post_edit: list[PostEditHook] = []

    def on_pre_tool(self, fn: PreToolHook) -> PreToolHook:
        self._pre_tool.append(fn)
        return fn

    def on_post_edit(self, fn: PostEditHook) -> PostEditHook:
        self._post_edit.append(fn)
        return fn

    def run_pre_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> dict[str, Any] | None:
        for fn in self._pre_tool:
            res = fn(tool_name, args, ctx)
            if isinstance(res, dict) and (res.get("ok") is False or res.get("blocked") or "error" in res):
                return err_result(
                    str(res.get("error") or f"Tool '{tool_name}' blocked by pre_tool hook."),
                    error_code=ERR_HOOK_BLOCKED,
                    hint=str(res.get("hint") or "Adjust tool arguments or check workspace policies."),
                )
        return None

    def run_post_edit(
        self,
        tool_name: str,
        rel_posix: str,
        resolved_path: Path,
        ctx: ToolContext,
    ) -> list[str]:
        diagnostics: list[str] = []
        for fn in self._post_edit:
            items = fn(tool_name, rel_posix, resolved_path, ctx)
            if items:
                diagnostics.extend(str(item) for item in items if str(item).strip())
        return diagnostics


def run_post_edit_sensors(
    tool_name: str,
    rel_posix: str,
    resolved_path: Path,
    content: str,
    ctx: ToolContext,
) -> tuple[bool, str | None, list[str]]:
    """Run built-in syntax checks, configured external linters, and post_edit hooks."""
    diagnostics: list[str] = []

    syntax_err = check_syntax(rel_posix, content)
    if syntax_err:
        diagnostics.append(syntax_err)

    for cmd in ctx.post_edit_commands:
        if not cmd:
            continue
        argv = [*cmd, str(resolved_path)]
        try:
            proc = subprocess.run(
                argv,
                cwd=ctx.workspace_root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if proc.returncode != 0:
                combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
                lines = [ln.strip() for ln in combined.splitlines() if ln.strip()][:8]
                msg = "; ".join(lines)[:500] if lines else f"{cmd[0]} exited with code {proc.returncode}"
                diagnostics.append(msg)
        except (OSError, subprocess.TimeoutExpired) as exc:
            diagnostics.append(f"post_edit sensor '{cmd[0]}' failed: {exc}")

    if ctx.hooks is not None and hasattr(ctx.hooks, "run_post_edit"):
        diagnostics.extend(ctx.hooks.run_post_edit(tool_name, rel_posix, resolved_path, ctx))

    return len(diagnostics) == 0, syntax_err, diagnostics
