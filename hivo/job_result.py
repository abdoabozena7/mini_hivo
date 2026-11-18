"""Verify and package a headless job's proposed changes without applying them."""

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


_RUNTIME_DIRS = {".hivo", ".mini_hivo", ".agent_backups", ".agent_evidence", ".agent_runs"}
_RUNTIME_FILES = {".agent_memory.json", ".agent_experiment.jsonl"}
_RUNTIME_NAMES = _RUNTIME_DIRS | _RUNTIME_FILES
_DEVICES = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    prefix + digit for prefix in ("com", "lpt") for digit in "123456789¹²³"
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_CHECK_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}")
_MAX_ENTRIES = 4096
_MAX_BYTES = 16 * 1024 * 1024

# These are Git file modes: other host permission bits are not portable patches.
_Inventory = dict[str, tuple[int, bytes]]


def _validate_path(path: str) -> None:
    if not isinstance(path, str) or any(
        char in '\\:<>"|?*' or ord(char) < 32 or ord(char) == 127 for char in path
    ):
        raise ValueError("unsupported project path")
    try:
        path.encode("utf-8")
    except UnicodeError:
        raise ValueError("unsupported project path") from None
    for part in path.split("/"):
        if (
            not part
            or part.endswith((".", " "))
            or part.casefold() == ".git"
            or part.split(".", 1)[0].rstrip(" ").casefold() in _DEVICES
        ):
            raise ValueError("unsupported project path")


def _linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ) or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)


def _checked_root(root: Path) -> Path:
    info = root.lstat()
    if _linked(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("invalid project snapshot root")
    return root.resolve(strict=True)


def _file_identity(info: os.stat_result) -> tuple:
    # Windows path and handle stats can disagree on st_ctime semantics.
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns


def _file_bytes(path: Path, info: os.stat_result) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        current = os.fstat(stream.fileno())
        if _linked(current) or _file_identity(current) != _file_identity(info):
            raise ValueError("project file changed during capture")
        data = stream.read(info.st_size + 1)
        final = os.fstat(stream.fileno())
        if (
            len(data) != info.st_size or _linked(final)
            or _file_identity(final) != _file_identity(current) or final.st_ctime_ns != current.st_ctime_ns
        ):
            raise ValueError("project file changed during capture")
    return data


def _inventory(root: Path, *, runtime_metadata: bool = False) -> _Inventory:
    files: _Inventory = {}
    pending = [("", root)]
    count = size = 0
    while pending:
        prefix, directory = pending.pop()
        seen = set()
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > _MAX_ENTRIES:
                    raise ValueError("project snapshot exceeds verification budget")
                path = prefix + entry.name
                _validate_path(path)
                folded = entry.name.casefold()
                if folded in seen:
                    raise ValueError("ambiguous project paths")
                seen.add(folded)
                # Windows DirEntry.stat omits inode, device and hardlink counts.
                info = os.lstat(entry.path)
                is_dir = stat.S_ISDIR(info.st_mode)
                if _linked(info) or not (is_dir or stat.S_ISREG(info.st_mode)):
                    raise ValueError("project links and special files are unsupported")
                if not prefix and folded in _RUNTIME_NAMES:
                    if not runtime_metadata or entry.name != folded or is_dir != (folded in _RUNTIME_DIRS):
                        raise ValueError("reserved controller metadata path")
                    continue
                if is_dir:
                    pending.append((path + "/", Path(entry.path)))
                    continue
                size += info.st_size
                if size > _MAX_BYTES:
                    raise ValueError("project snapshot exceeds verification budget")
                mode = 0o100755 if info.st_mode & stat.S_IXUSR else 0o100644
                files[path] = (mode, _file_bytes(Path(entry.path), info))
    return files


def _digest(files: _Inventory) -> str:
    digest = hashlib.sha256(b"hivo-job-snapshot-v1\0")
    for path, (mode, data) in sorted(files.items()):
        name = path.encode("utf-8")
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(mode.to_bytes(4, "big"))
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def snapshot_digest(root: str | Path) -> str:
    """Hash a quiescent project's portable paths, Git modes and exact file bytes.

    Only the explicitly named top-level controller metadata is excluded. Its
    subtrees are never entered. Empty directories are outside Git's file surface.
    """
    try:
        return _digest(_inventory(_checked_root(Path(root)), runtime_metadata=True))
    except (OSError, RuntimeError, TypeError):
        raise ValueError("project snapshot is unavailable") from None


def _matches(value, pattern: re.Pattern) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _scope(paths) -> set[str]:
    if not isinstance(paths, list) or not paths or len(paths) > _MAX_ENTRIES:
        raise ValueError("missing or invalid approved path scope")
    scope = set()
    for path in paths:
        _validate_path(path)
        if path.split("/", 1)[0].casefold() in _RUNTIME_NAMES or path.casefold() in scope:
            raise ValueError("invalid approved path scope")
        scope.add(path.casefold())
    return set(paths)


def _binding(job: dict, outcome: dict) -> tuple[str, str, set[str]]:
    if not isinstance(outcome, dict) or outcome.get("status") != "candidate":
        raise ValueError("missing candidate outcome")
    evidence = outcome.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("root_verified") is not True:
        raise ValueError("missing root verification evidence")
    for key in ("job_id", "attempt_id"):
        value = job.get(key)
        if not isinstance(value, str) or not value or evidence.get(key) != value:
            raise ValueError("candidate attests to a different job or attempt")
    revision = job.get("base_revision")
    if not _matches(revision, _GIT_OID) or evidence.get("base_revision") != revision:
        raise ValueError("candidate attests to a different base revision")

    decision, request = job.get("decision"), job.get("decision_request")
    plan_hash = evidence.get("plan_hash")
    if (
        not isinstance(decision, dict) or not isinstance(request, dict)
        or decision.get("kind") != "approve" or request.get("kind") != "approval"
        or not isinstance(request.get("decision_id"), str) or not request["decision_id"]
        or decision.get("decision_id") != request["decision_id"]
        or not _matches(plan_hash, _SHA256)
        or plan_hash != decision.get("plan_hash") or plan_hash != request.get("plan_hash")
    ):
        raise ValueError("candidate is not bound to the approved plan")

    checkpoint = job.get("checkpoint")
    if not isinstance(checkpoint, dict) or not _matches(checkpoint.get("base_sha256"), _SHA256):
        raise ValueError("missing approved base snapshot digest")
    allowed = _scope(checkpoint.get("allowed_paths"))
    if _scope(evidence.get("allowed_paths")) != allowed:
        raise ValueError("candidate path scope differs from approval")
    workspace_sha256 = evidence.get("workspace_sha256")
    if not _matches(workspace_sha256, _SHA256):
        raise ValueError("invalid candidate digest")
    return workspace_sha256, checkpoint["base_sha256"], allowed


def _write_snapshot(root: Path, files: _Inventory) -> None:
    root.mkdir()
    for path, (mode, data) in files.items():
        target = root.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(mode & 0o777)


def _git(scratch: Path, cwd: Path, args: list[str], data: bytes = b"") -> subprocess.CompletedProcess:
    program = "git.exe" if os.name == "nt" else "git"
    # Do not let Windows implicitly select an executable from the current directory.
    search = (Path(folder) / program for folder in os.get_exec_path() if Path(folder).is_absolute())
    git = next((path for path in search if path.is_file() and os.access(path, os.X_OK)), None)
    if git is None:
        raise ValueError("Git patch verification is unavailable")
    ceiling = str(scratch.parent)
    if os.pathsep in ceiling:
        raise ValueError("unsupported verifier staging path")
    env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR"}}
    env.update(
        LC_ALL="C", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
        GIT_ATTR_NOSYSTEM="1", GIT_CEILING_DIRECTORIES=ceiling,
    )
    try:
        return subprocess.run(
            [str(git.resolve(strict=True)), "--no-pager",
             "-c", "core.protectNTFS=true", "-c", "core.protectHFS=true",
             "-c", "core.quotePath=true", *args],
            cwd=cwd, env=env, input=data, capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Git patch verification is unavailable") from None


def _render_patch(scratch: Path) -> bytes:
    result = _git(scratch, scratch, [
        "diff", "--no-index", "--no-ext-diff", "--no-textconv", "--no-color",
        "--no-prefix", "--text", "--no-renames", "--full-index", "--", "a", "b",
    ])
    if result.returncode != 1 or not result.stdout:
        raise ValueError("could not produce a text patch")
    return result.stdout


def _behavior_checks(checker, job: dict, materialized: Path) -> list:
    try:
        receipt = checker(copy.deepcopy(job), materialized)
    except Exception:
        raise ValueError("independent behavior checker unavailable") from None
    if not isinstance(receipt, list) or not receipt:
        raise ValueError("independent behavior checks missing")
    verified = {}
    for check in receipt:
        check_id = check.get("check_id") if isinstance(check, dict) else None
        if not _matches(check_id, _CHECK_ID) or check_id in verified or check.get("passed") is not True:
            raise ValueError("independent behavior checks failed")
        verified[check_id] = {"check_id": check_id, "passed": True}
    return list(verified.values())


def verify_candidate(job: dict, base_dir: Path, work_dir: Path, outcome: dict, checker) -> dict:
    """Finalize only from the trusted runtime's stopped, disjoint attempt staging.

    The runtime binds base_dir to the registered commit and guards execution in
    the host-owned checker. The checker receives a separate replay below the
    candidate's trusted attempt scratch, never the candidate itself.
    """
    expected_sha256, base_sha256, allowed = _binding(job, outcome)
    try:
        base_root = _checked_root(Path(base_dir))
        work_root = _checked_root(Path(work_dir))
        if base_root.is_relative_to(work_root) or work_root.is_relative_to(base_root):
            raise ValueError("project snapshots are not separate")
        base = _inventory(base_root)
        if _digest(base) != base_sha256:
            raise ValueError("approved base snapshot is stale")
        candidate = _inventory(work_root, runtime_metadata=True)
        workspace_sha256 = _digest(candidate)
        if workspace_sha256 != expected_sha256:
            raise ValueError("candidate snapshot is stale")
        changed = sorted(path for path in base.keys() | candidate.keys() if base.get(path) != candidate.get(path))
        if not changed or not allowed.issuperset(changed):
            raise ValueError("no edits or edits outside the approved path scope")
        for path in changed:
            for snapshot in (base, candidate):
                if path in snapshot:
                    data = snapshot[path][1]
                    if b"\0" in data:
                        raise ValueError("only text changes can be exported")
                    data.decode("utf-8")

        with tempfile.TemporaryDirectory(prefix="job-result-", dir=work_root.parent) as name:
            scratch = Path(name)
            replay = scratch / "a"
            _write_snapshot(replay, base)
            _write_snapshot(scratch / "b", candidate)
            patch = _render_patch(scratch)
            applied = _git(scratch, replay, ["apply", "--whitespace=nowarn", "-p1", "-"], patch)
            if applied.returncode != 0 or _inventory(replay) != candidate:
                raise ValueError("delivered patch did not reproduce the candidate")
            checks = _behavior_checks(checker, job, replay)
            if _inventory(replay) != candidate:
                raise ValueError("checked snapshot changed during verification")

        return {
            "diff": patch.decode("utf-8"),
            "base_revision": job["base_revision"],
            "changed_paths": changed,
            "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "workspace_sha256": workspace_sha256,
            "checks": checks,
        }
    except UnicodeError:
        raise ValueError("only UTF-8 text changes can be exported") from None
    except (OSError, RuntimeError, TypeError):
        raise ValueError("project snapshots could not be verified") from None
