"""Deterministic, privacy-safe deliverable inventory and backend run reports."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any


DELIVERABLE_REPORT_SCHEMA_VERSION = "1.0"

_EXCLUDED_DIRS = frozenset({
    ".hivo",
    ".mini_hivo",
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    ".agent_evidence",
    ".agent_backups",
    ".agent_runs",
    ".runtime-proof",
})
_SCREENSHOT_SUFFIXES = frozenset({".png", ".jpg", ".webp"})
_DONE_TASK_STATUSES = frozenset({"done", "parent_verified", "verified", "completed"})
_FAILED_TASK_STATUSES = frozenset({
    "failed",
    "error",
    "blocked",
    "provider_failure",
    "too_broad",
    "cancelled",
    "canceled",
    "aborted",
    "rejected",
})

_WINDOWS_ABS_PATH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:[\\/][^\s\"'<>|]+)+")
_UNIX_HOME_PATH_RE = re.compile(r"/(?:Users|home)/[^\s/\"'<>|]+(?:/[^\s\"'<>|]+)*")
_READ_CHUNK_BYTES = 65536


def _is_linked(info: os.stat_result) -> bool:
    if stat.S_ISLNK(info.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(info, "st_file_attributes", 0) & reparse_flag)


def _is_excluded_dir_name(name: str) -> bool:
    folded = name.casefold()
    return folded in _EXCLUDED_DIRS or folded.startswith(".agent_")


def _is_excluded_file_name(name: str) -> bool:
    folded = name.casefold()
    return folded in _EXCLUDED_DIRS or folded.startswith(".agent_")


def _validate_relative_posix_path(rel_path: str) -> str:
    if not isinstance(rel_path, str) or not rel_path:
        raise ValueError("deliverable path must be a non-empty string")
    if "\\" in rel_path or rel_path.startswith("/"):
        raise ValueError(f"non-relative or non-POSIX path rejected: {rel_path!r}")
    if re.match(r"^[A-Za-z]:", rel_path):
        raise ValueError(f"host drive path rejected: {rel_path!r}")
    posix = PurePosixPath(rel_path)
    if posix.is_absolute() or ".." in posix.parts or "." in posix.parts:
        raise ValueError(f"unsafe relative path rejected: {rel_path!r}")
    return rel_path


def _hash_regular_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total_bytes = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            total_bytes += len(chunk)
            digest.update(chunk)
    return total_bytes, digest.hexdigest()


def _sanitize_text_paths(text: str, workspace_root: Path | None = None) -> str:
    cleaned = str(text)
    if workspace_root is not None:
        for variant in (str(workspace_root), workspace_root.as_posix()):
            if len(variant) > 3 and variant in cleaned:
                cleaned = cleaned.replace(variant + "\\", "")
                cleaned = cleaned.replace(variant + "/", "")
                cleaned = cleaned.replace(variant, ".")
    cleaned = _WINDOWS_ABS_PATH_RE.sub("<redacted-path>", cleaned)
    cleaned = _UNIX_HOME_PATH_RE.sub("<redacted-path>", cleaned)
    return cleaned


def _non_negative_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return default
    return value


def _non_negative_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0:
        return default
    return round(numeric, 6)


def _extract_tokens(metrics: dict[str, Any]) -> tuple[int, int]:
    provider_usage = metrics.get("provider_usage")
    usage_total: dict[str, Any] = {}
    if isinstance(provider_usage, dict):
        nested_total = provider_usage.get("total")
        usage_total = nested_total if isinstance(nested_total, dict) else provider_usage

    input_raw = metrics.get("input_tokens")
    if isinstance(input_raw, bool) or not isinstance(input_raw, int) or input_raw < 0:
        input_raw = metrics.get("prompt_eval_count")
    if isinstance(input_raw, bool) or not isinstance(input_raw, int) or input_raw < 0:
        input_raw = usage_total.get("prompt_eval_count")

    output_raw = metrics.get("output_tokens")
    if isinstance(output_raw, bool) or not isinstance(output_raw, int) or output_raw < 0:
        output_raw = metrics.get("eval_count")
    if isinstance(output_raw, bool) or not isinstance(output_raw, int) or output_raw < 0:
        output_raw = usage_total.get("eval_count")

    return _non_negative_int(input_raw, 0), _non_negative_int(output_raw, 0)


def _summarize_task_ledger(task_ledger: dict | list | None) -> dict[str, int]:
    if task_ledger is None:
        return {"total_nodes": 0, "done_nodes": 0, "failed_nodes": 0}

    if isinstance(task_ledger, dict) and {"total_nodes", "done_nodes", "failed_nodes"}.issubset(
        task_ledger.keys()
    ):
        return {
            "total_nodes": _non_negative_int(task_ledger.get("total_nodes"), 0),
            "done_nodes": _non_negative_int(task_ledger.get("done_nodes"), 0),
            "failed_nodes": _non_negative_int(task_ledger.get("failed_nodes"), 0),
        }

    statuses: list[str] = []
    if isinstance(task_ledger, (list, tuple)):
        for node in task_ledger:
            if isinstance(node, dict):
                statuses.append(str(node.get("status", "")).strip().lower())
    elif isinstance(task_ledger, dict) and task_ledger:
        if isinstance(task_ledger.get("tasks"), (list, tuple)):
            return _summarize_task_ledger(list(task_ledger["tasks"]))
        if isinstance(task_ledger.get("tasks"), dict):
            return _summarize_task_ledger(task_ledger["tasks"])
        if isinstance(task_ledger.get("nodes"), (list, tuple)):
            return _summarize_task_ledger(list(task_ledger["nodes"]))
        if all(isinstance(value, dict) for value in task_ledger.values()):
            for node in task_ledger.values():
                statuses.append(str(node.get("status", "")).strip().lower())
        elif "status" in task_ledger and isinstance(task_ledger.get("status"), str):
            statuses.append(task_ledger["status"].strip().lower())
            children = task_ledger.get("children")
            if isinstance(children, (list, tuple)):
                for child in children:
                    if isinstance(child, dict):
                        child_summary = _summarize_task_ledger(child)
                        statuses.extend(
                            ["done"] * child_summary["done_nodes"]
                            + ["failed"] * child_summary["failed_nodes"]
                            + ["pending"]
                            * (
                                child_summary["total_nodes"]
                                - child_summary["done_nodes"]
                                - child_summary["failed_nodes"]
                            )
                        )
        elif all(isinstance(value, str) for value in task_ledger.values()):
            statuses.extend(value.strip().lower() for value in task_ledger.values())

    done_nodes = sum(1 for item in statuses if item in _DONE_TASK_STATUSES)
    failed_nodes = sum(1 for item in statuses if item in _FAILED_TASK_STATUSES)
    return {
        "total_nodes": len(statuses),
        "done_nodes": done_nodes,
        "failed_nodes": failed_nodes,
    }


def inventory_workspace_deliverables(workspace: Path) -> list[dict]:
    """Return sorted relative POSIX file entries for user deliverables in workspace."""
    root = Path(workspace).resolve()
    if not root.exists() or not root.is_dir():
        return []

    deliverables: list[dict[str, Any]] = []
    for current_dir, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current_dir)
        kept_dirs: list[str] = []
        for dir_name in sorted(dir_names):
            if _is_excluded_dir_name(dir_name):
                continue
            candidate_dir = current_path / dir_name
            try:
                dir_info = candidate_dir.lstat()
            except OSError:
                continue
            if _is_linked(dir_info) or not stat.S_ISDIR(dir_info.st_mode):
                continue
            kept_dirs.append(dir_name)
        dir_names[:] = kept_dirs

        for file_name in sorted(file_names):
            if _is_excluded_file_name(file_name):
                continue
            file_path = current_path / file_name
            try:
                file_info = file_path.lstat()
                if _is_linked(file_info) or not stat.S_ISREG(file_info.st_mode):
                    continue
                resolved = file_path.resolve()
                if not resolved.is_relative_to(root):
                    continue
                rel_posix = _validate_relative_posix_path(file_path.relative_to(root).as_posix())
                size_bytes, sha256_hex = _hash_regular_file(file_path)
            except (OSError, ValueError):
                continue
            deliverables.append(
                {
                    "path": rel_posix,
                    "size_bytes": size_bytes,
                    "sha256": sha256_hex,
                }
            )

    deliverables.sort(key=lambda entry: entry["path"])
    return deliverables


def find_workspace_evidence_screenshots(workspace: Path) -> list[str]:
    """Return sorted relative POSIX paths to screenshots under .agent_evidence."""
    root = Path(workspace).resolve()
    if not root.exists() or not root.is_dir():
        return []

    evidence_dir = root / ".agent_evidence"
    try:
        evidence_info = evidence_dir.lstat()
    except OSError:
        return []
    if _is_linked(evidence_info) or not stat.S_ISDIR(evidence_info.st_mode):
        return []

    screenshots: list[str] = []
    for current_dir, dir_names, file_names in os.walk(evidence_dir, topdown=True, followlinks=False):
        current_path = Path(current_dir)
        kept_dirs: list[str] = []
        for dir_name in sorted(dir_names):
            candidate_dir = current_path / dir_name
            try:
                dir_info = candidate_dir.lstat()
            except OSError:
                continue
            if _is_linked(dir_info) or not stat.S_ISDIR(dir_info.st_mode):
                continue
            kept_dirs.append(dir_name)
        dir_names[:] = kept_dirs

        for file_name in sorted(file_names):
            file_path = current_path / file_name
            if file_path.suffix.lower() not in _SCREENSHOT_SUFFIXES:
                continue
            try:
                file_info = file_path.lstat()
                if _is_linked(file_info) or not stat.S_ISREG(file_info.st_mode):
                    continue
                resolved = file_path.resolve()
                if not resolved.is_relative_to(root):
                    continue
                rel_posix = _validate_relative_posix_path(file_path.relative_to(root).as_posix())
            except (OSError, ValueError):
                continue
            screenshots.append(rel_posix)

    screenshots.sort()
    return screenshots


def build_deliverable_run_report(
    *,
    run_id: str,
    model: str,
    mode: str,
    status: str,
    exit_code: int,
    summary: str,
    workspace: Path,
    run_metrics: dict | None = None,
    task_ledger: dict | list | None = None,
) -> dict:
    """Build a JSON-serializable, privacy-safe deliverable backend report."""
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise ValueError("exit_code must be an integer")

    workspace_path = Path(workspace)
    resolved_workspace = workspace_path.resolve()
    normalized_status = str(status).strip()
    metrics = run_metrics if isinstance(run_metrics, dict) else {}
    budget = metrics.get("run_budget") if isinstance(metrics.get("run_budget"), dict) else {}

    model_calls = _non_negative_int(
        metrics.get("model_calls", budget.get("model_calls", 0)),
        0,
    )
    tool_calls = _non_negative_int(
        metrics.get("tool_calls", budget.get("tool_calls", 0)),
        0,
    )
    elapsed_seconds = _non_negative_float(
        metrics.get("elapsed_seconds", budget.get("elapsed_seconds", 0.0)),
        0.0,
    )
    input_tokens, output_tokens = _extract_tokens(metrics)

    telemetry = {
        "model_calls": model_calls,
        "tool_calls": tool_calls,
        "splits": _non_negative_int(metrics.get("splits"), 0),
        "max_depth": _non_negative_int(metrics.get("max_depth"), 0),
        "leaf_tasks": _non_negative_int(metrics.get("leaf_tasks"), 0),
        "repairer_calls": _non_negative_int(metrics.get("repairer_calls"), 0),
        "browser_checks": _non_negative_int(metrics.get("browser_checks"), 0),
        "evidence_licensed_corrections": _non_negative_int(
            metrics.get("evidence_licensed_corrections"),
            0,
        ),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "elapsed_seconds": elapsed_seconds,
    }

    deliverables = inventory_workspace_deliverables(workspace_path)
    screenshots = find_workspace_evidence_screenshots(workspace_path)

    return {
        "schema_version": DELIVERABLE_REPORT_SCHEMA_VERSION,
        "run_id": str(run_id),
        "model": str(model),
        "mode": str(mode),
        "status": normalized_status,
        "exit_code": exit_code,
        "verified": bool(normalized_status == "done" and exit_code == 0),
        "summary": _sanitize_text_paths(summary, resolved_workspace),
        "telemetry": telemetry,
        "deliverables": deliverables,
        "screenshots": screenshots,
        "task_summary": _summarize_task_ledger(task_ledger),
    }


def write_deliverable_run_report(report: dict, output_path: Path) -> Path:
    """Write a deliverable run report as formatted UTF-8 JSON and return output_path."""
    if not isinstance(report, dict):
        raise ValueError("report must be a dict")
    for item in report.get("deliverables", []):
        if isinstance(item, dict) and "path" in item:
            _validate_relative_posix_path(item["path"])
    for shot in report.get("screenshots", []):
        _validate_relative_posix_path(shot)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    target.write_text(serialized, encoding="utf-8")
    return target
