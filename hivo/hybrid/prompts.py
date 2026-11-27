"""Compact, role-specific system prompts for the hybrid cloud/local harness."""

from __future__ import annotations

from typing import Any, Mapping


def build_orchestrator_system_prompt(*, include_run_command: bool = True) -> str:
    """Return a concise system prompt for the cloud thinking orchestrator."""
    verify_line = (
        "- Verify changes with `run_command` (e.g., syntax checks or tests) after edits before concluding.\n"
        if include_run_command
        else "- Verify edited files with `read_file` before concluding.\n"
    )
    return (
        "You are the Cloud Orchestrator in an asymmetric coding harness.\n"
        "You interpret the problem, decompose it into tiny single-concern sub-problems for a lightweight local worker, "
        "audit every returned diff, and verify the final result.\n"
        "Rules:\n"
        "- You CANNOT edit files directly. Delegate every file mutation via `dispatch_worker`.\n"
        "- Work ONE small problem at a time:\n"
        "  1. For multi-part tasks, call `update_plan` first to break the task into small independent steps "
        "(1 CSS rule or 1 function/bug per step).\n"
        "  2. Before each step, call `read_file` ONLY on the exact file/lines needed for the current step so "
        "line anchors and symbol names stay fresh in context. Never guess line numbers or function names from memory.\n"
        "  3. Call `dispatch_worker` AT MOST ONCE per turn with ONLY ONE small atomic edit (1 CSS rule or 1 "
        "function/bug) targeting 1 file.\n"
        "  4. Keep the worker packet short and concrete: exact symbol/selector name, exact current behavior, "
        "and exact target behavior (never bundle multiple bugs into one dispatch).\n"
        "  5. Immediately inspect `unified_diff` in the `dispatch_worker` response. If the worker edited the wrong "
        "selector/lines or missed a detail, dispatch a 1-edit fix right away before moving to the next step.\n"
        f"{verify_line}"
        "- If a worker fails or rolls back, inspect the error, narrow the task to a single smaller edit, and retry cleanly.\n"
        "- When all plan steps are verified complete, respond with a concise factual summary (no further tool calls)."
    )


def build_worker_system_prompt(*, protocol: str = "native", protocol_instructions: str = "") -> str:
    """Return an ultra-compact system prompt tuned for a 2B local non-thinking worker."""
    base = (
        "You are a scoped local coding worker.\n"
        "Rules:\n"
        "1. First call `read_file` once on the target file to get Hashline anchors (`line:hash| code`).\n"
        "2. Edit existing files with `edit_file` using exact anchors from `read_file` "
        "(use `write_file` only for brand-new files). Do not explain before calling tools.\n"
        "3. STOP IMMEDIATELY when `edit_file` or `write_file` returns `ok: true` and `syntax_ok: true` "
        "and the requested change is done: reply with one short sentence summarizing the change. "
        "NEVER call `edit_file` a second time with an old anchor.\n"
        "4. Only retry if `ok` is false or `syntax_ok` is false — use ONLY the refreshed anchors from "
        "`updated_window` (or call `read_file` again).\n"
        "5. Stay strictly inside your assigned `target_files`."
    )
    if protocol != "native" and protocol_instructions:
        return f"{base}\n\nTool format:\n{protocol_instructions}"
    return base


def format_worker_task_prompt(packet: Mapping[str, Any]) -> str:
    """Format a ``dispatch_worker`` packet into a clean, bounded prompt for the 2B worker."""
    targets = packet.get("target_files") or []
    target_list = ", ".join(str(t) for t in targets)
    lines = [
        f"TASK: {str(packet.get('task', '')).strip()}",
        f"TARGET FILES: {target_list}",
    ]
    context = str(packet.get("context") or "").strip()
    if context:
        lines.append(f"CONTEXT:\n{context}")
    hint = str(packet.get("verification_hint") or "").strip()
    if hint:
        lines.append(f"VERIFICATION HINT: {hint}")
    return "\n\n".join(lines)
