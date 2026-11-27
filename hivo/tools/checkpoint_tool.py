"""Workspace checkpoint and deterministic 1-step rollback tool: ``checkpoint``."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

from .base import (
    ERR_INFRA,
    ERR_NOT_FOUND,
    ERR_ORACLE_LOCKED,
    ERR_TOOL_SCHEMA,
    ToolContext,
    ToolSpec,
    atomic_write_bytes,
    effective_scratch_dir,
    err_result,
    is_protected_path,
    is_secret_path,
    load_gitignore_matcher,
    ok_result,
)

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
_CHUNK_SIZE = 65536


def _hash_file_streaming(file_path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    total_size = 0
    with file_path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
            total_size += len(chunk)
    return hasher.hexdigest(), total_size


def _copy_file_atomic(src_path: Path, dst_path: Path) -> None:
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    tmp_file = None
    try:
        tmp_file = tempfile.NamedTemporaryFile(
            mode="wb",
            dir=dst_path.parent,
            prefix=".tmp_cp_",
            delete=False,
        )
        tmp_path = Path(tmp_file.name)
        with src_path.open("rb") as src_fh:
            shutil.copyfileobj(src_fh, tmp_file, length=_CHUNK_SIZE)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
        tmp_file.close()
        tmp_file = None
        os.replace(tmp_path, dst_path)
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


def _checkpoints_root(ctx: ToolContext) -> Path:
    return effective_scratch_dir(ctx) / "checkpoints"


def _compute_tree_hash(entries: list[dict[str, Any]]) -> str:
    sorted_entries = sorted(entries, key=lambda item: item["path"])
    payload = "\n".join(f"{item['path']}:{item['sha256']}" for item in sorted_entries).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _snapshot_workspace_files(ctx: ToolContext) -> list[dict[str, Any]]:
    matcher = load_gitignore_matcher(ctx.workspace_root)
    files: list[dict[str, Any]] = []
    for root, dirs, filenames in os.walk(ctx.workspace_root):
        root_path = Path(root)
        kept_dirs: list[str] = []
        for d in sorted(dirs):
            d_path = root_path / d
            if d_path.is_symlink():
                continue
            try:
                d_res = d_path.resolve()
            except OSError:
                continue
            if not d_res.is_relative_to(ctx.workspace_root):
                continue
            d_rel = d_res.relative_to(ctx.workspace_root).as_posix()
            if matcher.is_ignored(d_rel, is_dir=True):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for fname in sorted(filenames):
            f_path = root_path / fname
            if f_path.is_symlink():
                continue
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
            try:
                sha, size = _hash_file_streaming(f_res)
            except OSError:
                continue
            files.append({
                "path": f_rel,
                "sha256": sha,
                "size": size,
                "_src_path": f_res,
            })
    files.sort(key=lambda item: item["path"])
    return files


def _read_git_head(workspace_root: Path) -> str | None:
    if not (workspace_root / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace_root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None


def _evict_pycache_for_python_file(target: Path) -> None:
    """Remove stale ``__pycache__`` entries for a restored or deleted ``.py`` file."""
    if target.suffix.casefold() != ".py":
        return
    cache_dir = target.parent / "__pycache__"
    if not cache_dir.is_dir():
        return
    for pyc in cache_dir.glob(f"{target.stem}.*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


def _handle_checkpoint(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    action: str = args["action"]
    raw_id: str = (args.get("checkpoint_id", "") or "").strip()
    root = _checkpoints_root(ctx)
    blobs_dir = root / "blobs"
    manifests_dir = root / "manifests"

    if action == "list":
        if not manifests_dir.is_dir():
            return ok_result({"checkpoints": [], "count": 0})
        listed: list[dict[str, Any]] = []
        for mfile in sorted(manifests_dir.glob("*.json")):
            try:
                data = json.loads(mfile.read_text(encoding="utf-8"))
                listed.append({
                    "checkpoint_id": data.get("checkpoint_id"),
                    "created_at": data.get("created_at"),
                    "tree_hash": data.get("tree_hash"),
                    "file_count": len(data.get("files", [])),
                    "git_head": data.get("git_head"),
                })
            except (OSError, json.JSONDecodeError):
                continue
        listed.sort(key=lambda item: str(item.get("created_at") or ""))
        return ok_result({"checkpoints": listed, "count": len(listed)})

    if action == "create":
        blobs_dir.mkdir(parents=True, exist_ok=True)
        manifests_dir.mkdir(parents=True, exist_ok=True)

        if raw_id:
            cp_id = _SAFE_ID_RE.sub("_", raw_id).strip("._-")
            if not cp_id:
                return err_result(
                    "Invalid checkpoint_id.",
                    error_code=ERR_TOOL_SCHEMA,
                    hint="Provide alphanumeric characters in checkpoint_id or omit it for an auto-generated ID.",
                )
        else:
            existing = list(manifests_dir.glob("*.json"))
            cp_id = f"cp_{len(existing) + 1:03d}"
            while (manifests_dir / f"{cp_id}.json").exists():
                cp_id += "_n"

        entries = _snapshot_workspace_files(ctx)
        manifest_files: list[dict[str, Any]] = []
        for item in entries:
            blob_path = blobs_dir / item["sha256"]
            if not blob_path.exists():
                _copy_file_atomic(item["_src_path"], blob_path)
            manifest_files.append({
                "path": item["path"],
                "sha256": item["sha256"],
                "size": item["size"],
            })

        tree_hash = _compute_tree_hash(manifest_files)
        manifest = {
            "checkpoint_id": cp_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_head": _read_git_head(ctx.workspace_root),
            "tree_hash": tree_hash,
            "files": manifest_files,
        }
        atomic_write_bytes(
            manifests_dir / f"{cp_id}.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        )
        return ok_result({
            "action": "create",
            "checkpoint_id": cp_id,
            "tree_hash": tree_hash,
            "file_count": len(manifest_files),
            "git_head": manifest["git_head"],
        })

    # rollback
    if not raw_id:
        return err_result(
            "Parameter 'checkpoint_id' is required for action='rollback'.",
            error_code=ERR_TOOL_SCHEMA,
            hint="Call checkpoint(action='list') to see available checkpoint IDs.",
        )

    cp_id = _SAFE_ID_RE.sub("_", raw_id).strip("._-")
    manifest_path = manifests_dir / f"{cp_id}.json"
    if not manifest_path.is_file():
        return err_result(
            f"Checkpoint '{raw_id}' does not exist.",
            error_code=ERR_NOT_FOUND,
            hint="Call checkpoint(action='list') to inspect valid checkpoint IDs.",
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return err_result(
            f"Could not read checkpoint '{cp_id}': {exc}.",
            error_code=ERR_INFRA,
            hint="Create a fresh checkpoint or inspect scratch storage.",
        )

    snap_entries = {item["path"]: item for item in manifest.get("files", [])}
    current_entries = {item["path"]: item for item in _snapshot_workspace_files(ctx)}

    # Pre-check blobs and protected_paths before modifying any workspace file
    to_restore: list[tuple[str, Path]] = []
    for rel, snap_item in sorted(snap_entries.items()):
        cur_item = current_entries.get(rel)
        if cur_item is not None and cur_item["sha256"] == snap_item["sha256"]:
            continue
        if is_protected_path(rel, ctx):
            return err_result(
                f"Rollback cannot modify oracle-locked path '{rel}'.",
                error_code=ERR_ORACLE_LOCKED,
                hint="Protected files cannot be altered by rollback.",
            )
        blob_path = blobs_dir / snap_item["sha256"]
        if not blob_path.is_file():
            return err_result(
                f"Missing blob for '{rel}' in checkpoint '{cp_id}'.",
                error_code=ERR_INFRA,
                hint="Checkpoint storage is incomplete.",
            )
        to_restore.append((rel, blob_path))

    to_delete: list[str] = []
    for rel in sorted(current_entries):
        if rel not in snap_entries:
            if is_protected_path(rel, ctx):
                return err_result(
                    f"Rollback cannot delete oracle-locked path '{rel}'.",
                    error_code=ERR_ORACLE_LOCKED,
                    hint="Protected files cannot be removed by rollback.",
                )
            to_delete.append(rel)

    restored_paths: list[str] = []
    for rel, blob_path in to_restore:
        target = ctx.workspace_root / rel
        _copy_file_atomic(blob_path, target)
        _evict_pycache_for_python_file(target)
        restored_paths.append(rel)

    deleted_paths: list[str] = []
    for rel in to_delete:
        target = ctx.workspace_root / rel
        if target.exists() and target.is_file():
            target.unlink()
            _evict_pycache_for_python_file(target)
            deleted_paths.append(rel)
            parent = target.parent
            while parent != ctx.workspace_root and parent.exists():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent

    after_entries = _snapshot_workspace_files(ctx)
    after_tree_hash = _compute_tree_hash([{"path": item["path"], "sha256": item["sha256"]} for item in after_entries])

    return ok_result({
        "action": "rollback",
        "checkpoint_id": cp_id,
        "restored_files": restored_paths,
        "deleted_files": deleted_paths,
        "tree_hash": after_tree_hash,
        "expected_tree_hash": manifest.get("tree_hash"),
        "exact_match": after_tree_hash == manifest.get("tree_hash"),
    })


CHECKPOINT_SPEC = ToolSpec(
    name="checkpoint",
    description=(
        "Create external workspace snapshots and perform deterministic 1-step rollback "
        "(stored outside the repository so zero untracked artifacts pollute git status)."
    ),
    effect="control",
    model_tier="orchestrator_only",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "rollback", "list"],
                "description": "Checkpoint operation: create a snapshot, rollback to one, or list snapshots.",
            },
            "checkpoint_id": {
                "type": "string",
                "default": "",
                "description": "Optional identifier for create; required for rollback.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    },
    handler=_handle_checkpoint,
)
