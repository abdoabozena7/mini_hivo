"""Orchestrator control tool units: ``update_plan``, ``dispatch_worker``, ``ask_user``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import (
    ERR_INFRA,
    ERR_TOOL_SCHEMA,
    ToolContext,
    ToolSpec,
    err_result,
    ok_result,
    resolve_workspace_path,
)

PLAN_STATUSES: tuple[str, ...] = ("pending", "in_progress", "done", "blocked")


@dataclass
class PlanState:
    """In-memory structured plan container updated by ``update_plan``."""

    steps: list[dict[str, Any]] = field(default_factory=list)

    def update(self, new_steps: list[dict[str, Any]]) -> None:
        self.steps = [dict(step) for step in new_steps]

    def counts(self) -> dict[str, int]:
        summary = {status: 0 for status in PLAN_STATUSES}
        for step in self.steps:
            st = str(step.get("status", "pending"))
            if st in summary:
                summary[st] += 1
        return summary


def _handle_update_plan(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if ctx.plan_store is None:
        return err_result(
            "No plan_store is configured in ToolContext.",
            hint="Attach a PlanState or plan callback to ToolContext.plan_store before calling update_plan.",
        )

    raw_steps: list[dict[str, Any]] = args["steps"]
    seen_ids: set[str] = set()
    normalized_steps: list[dict[str, Any]] = []

    for idx, step in enumerate(raw_steps):
        step_id = step["id"].strip()
        title = step["title"].strip()
        status = step["status"]
        if not step_id:
            return err_result(
                f"Plan step at index {idx} has an empty 'id'.",
                error_code=ERR_TOOL_SCHEMA,
                hint="Provide a unique non-empty string 'id' for each plan step.",
            )
        if step_id in seen_ids:
            return err_result(
                f"Duplicate plan step id {step_id!r}.",
                error_code=ERR_TOOL_SCHEMA,
                hint="Give every step in 'steps' a unique 'id'.",
            )
        seen_ids.add(step_id)
        if not title:
            return err_result(
                f"Plan step {step_id!r} has an empty 'title'.",
                error_code=ERR_TOOL_SCHEMA,
                hint="Provide a concise descriptive 'title' for each step.",
            )

        norm_files: list[str] = []
        seen_files: set[str] = set()
        for raw_file in step.get("files", []):
            _, rel_posix, path_err = resolve_workspace_path(
                raw_file,
                ctx,
                check_allowed=False,
                allow_root=False,
            )
            if path_err is not None or rel_posix is None:
                return path_err  # type: ignore[return-value]
            if rel_posix not in seen_files:
                seen_files.add(rel_posix)
                norm_files.append(rel_posix)

        normalized_steps.append({
            "id": step_id,
            "title": title,
            "status": status,
            "files": norm_files,
        })

    store = ctx.plan_store
    if isinstance(store, PlanState) or hasattr(store, "update"):
        store.update(normalized_steps)
        counts = store.counts() if hasattr(store, "counts") else None
    elif callable(store):
        store(normalized_steps)
        counts = None
    elif isinstance(store, list):
        store[:] = [dict(s) for s in normalized_steps]
        counts = None
    elif isinstance(store, dict):
        store["steps"] = [dict(s) for s in normalized_steps]
        counts = None
    else:
        return err_result(
            "Unsupported ToolContext.plan_store type.",
            hint="Use PlanState, a list, a dict, or a callable in ToolContext.plan_store.",
        )

    if counts is None:
        counts = {st: sum(1 for s in normalized_steps if s["status"] == st) for st in PLAN_STATUSES}

    return ok_result(
        {
            "step_count": len(normalized_steps),
            "counts": counts,
            "steps": normalized_steps,
        }
    )


def _handle_dispatch_worker(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    task = args["task"].strip()
    if not task:
        return err_result(
            "Worker task description cannot be empty.",
            error_code=ERR_TOOL_SCHEMA,
            hint="Provide a concrete, bounded task packet in 'task'.",
        )

    norm_targets: list[str] = []
    seen_targets: set[str] = set()
    for raw_target in args["target_files"]:
        _, rel_posix, path_err = resolve_workspace_path(
            raw_target,
            ctx,
            check_allowed=False,
            allow_root=False,
        )
        if path_err is not None or rel_posix is None:
            return path_err  # type: ignore[return-value]
        if rel_posix not in seen_targets:
            seen_targets.add(rel_posix)
            norm_targets.append(rel_posix)

    if ctx.worker_dispatcher is None or not callable(ctx.worker_dispatcher):
        return err_result(
            "No worker_dispatcher is configured in ToolContext.",
            hint="Attach a callable worker_dispatcher to ToolContext before calling dispatch_worker.",
        )

    packet = {
        "task": task,
        "target_files": norm_targets,
        "context": args.get("context", "") or "",
        "verification_hint": args.get("verification_hint", "") or "",
        "allow_delete": bool(args.get("allow_delete", False)),
    }

    raw_result = ctx.worker_dispatcher(packet)
    if not isinstance(raw_result, dict):
        return err_result(
            "worker_dispatcher returned an invalid non-dict result.",
            hint="Ensure worker_dispatcher returns a dictionary with status and modified_files.",
        )

    modified = raw_result.get("modified_files", [])
    if not isinstance(modified, list):
        modified = []

    normalized_result = {
        "status": str(raw_result.get("status", "unknown")),
        "modified_files": [str(p) for p in modified],
        "diff_summary": str(raw_result.get("diff_summary", "")),
        "error": raw_result.get("error"),
    }
    return ok_result(normalized_result)


def _handle_ask_user(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    question = args["question"].strip()
    if not question:
        return err_result(
            "Question text cannot be empty.",
            error_code=ERR_TOOL_SCHEMA,
            hint="Ask a clear, specific clarification or approval question.",
        )

    options: list[str] = []
    for raw_opt in args.get("options", []):
        cleaned = raw_opt.strip()
        if not cleaned:
            return err_result(
                "Options passed to ask_user must be non-empty strings.",
                error_code=ERR_TOOL_SCHEMA,
                hint="Remove blank entries from 'options' or omit 'options'.",
            )
        options.append(cleaned)

    if ctx.user_prompter is None or not callable(ctx.user_prompter):
        return err_result(
            "No user_prompter is configured in ToolContext.",
            hint="Attach a callable user_prompter to ToolContext before calling ask_user.",
        )

    answer = ctx.user_prompter(question, options)
    return ok_result(
        {
            "question": question,
            "options": options,
            "answer": "" if answer is None else str(answer),
        }
    )


UPDATE_PLAN_SPEC = ToolSpec(
    name="update_plan",
    description="Update the structured task decomposition and step statuses for this session.",
    effect="control",
    model_tier="orchestrator_only",
    parameters={
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "description": "Ordered list of plan steps.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "status": {"type": "string", "enum": list(PLAN_STATUSES)},
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": [],
                        },
                    },
                    "required": ["id", "title", "status"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["steps"],
        "additionalProperties": False,
    },
    handler=_handle_update_plan,
)

DISPATCH_WORKER_SPEC = ToolSpec(
    name="dispatch_worker",
    description="Delegate a bounded coding subtask on explicit target files to a worker agent.",
    effect="control",
    model_tier="orchestrator_only",
    parameters={
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Clear, bounded instruction for the worker."},
            "target_files": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
                "description": "Workspace-relative target files the worker is allowed to inspect/edit.",
            },
            "context": {
                "type": "string",
                "default": "",
                "description": "Relevant interfaces, signatures, or constraints needed by the worker.",
            },
            "verification_hint": {
                "type": "string",
                "default": "",
                "description": "Optional note on how the change will be verified.",
            },
            "allow_delete": {
                "type": "boolean",
                "default": False,
                "description": "Set true only if the subtask explicitly requires deleting a target file.",
            },
        },
        "required": ["task", "target_files"],
        "additionalProperties": False,
    },
    handler=_handle_dispatch_worker,
)

ASK_USER_SPEC = ToolSpec(
    name="ask_user",
    description="Pause and ask the user a clarification or approval question.",
    effect="control",
    model_tier="orchestrator_only",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Question to present to the user."},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "Optional list of suggested choices.",
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    },
    handler=_handle_ask_user,
)
