"""Workspace decontamination, network-isolation args, and patch anti-tamper checks.

Stdlib-only module (zero imports from legacy ``mini.py``) enforcing Stage 0
anti-cheating boundaries from ``dev_rules/benchmarking_rules.md``.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
import shutil
import stat
import subprocess
from typing import Any, Sequence

_VALID_NETWORK_MODES = frozenset({"none", "allowlist_proxy"})


def _handle_remove_readonly(func: Any, path: str, _exc: Any) -> None:
    """Clear read-only bits (common inside ``.git/objects`` on Windows) before unlinking."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    func(path)


def _rmtree_force(path: Path) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(path, onexc=_handle_remove_readonly)
    except TypeError:  # Python < 3.12 fallback
        shutil.rmtree(path, onerror=_handle_remove_readonly)


def _run_git(args: Sequence[str], *, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def docker_network_args(network_mode: str = "none") -> list[str]:
    """Return validated Docker CLI networking flags for sealed solve/grading containers."""
    mode = network_mode.strip().lower()
    if mode not in _VALID_NETWORK_MODES:
        raise ValueError(
            f"Unsupported benchmark network_mode {network_mode!r}; expected one of {sorted(_VALID_NETWORK_MODES)}"
        )
    if mode == "none":
        return ["--network", "none"]
    return ["--network", "allowlist_proxy"]


def strip_git_and_reinit(
    repo_dir: str | Path,
    *,
    commit_message: str = "benchmark baseline",
) -> dict[str, Any]:
    """Delete ``.git`` history/remotes/reflogs and re-initialize as 1 fresh orphan commit.

    Prevents agents from mining future commits, reflogs, tags, or dangling git objects
    (Cursor / arXiv:2611.10404 Tier 1–2 runtime reward hacking).
    """
    root = Path(repo_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Repository directory does not exist: {root}")

    git_dir = root / ".git"
    if git_dir.is_file():
        git_dir.unlink()
    elif git_dir.is_dir():
        _rmtree_force(git_dir)

    init_proc = _run_git(["init", "-q"], cwd=root)
    if init_proc.returncode != 0:
        raise RuntimeError(f"git init failed in {root}: {init_proc.stderr.strip()}")

    config_pairs = (
        ("user.name", "Mini Hivo Benchmark"),
        ("user.email", "benchmark@mini-hivo.local"),
        ("core.filemode", "false"),
        ("core.symlinks", "false"),
        ("core.autocrlf", "false"),
        ("commit.gpgsign", "false"),
    )
    for key, val in config_pairs:
        cfg_proc = _run_git(["config", key, val], cwd=root)
        if cfg_proc.returncode != 0:
            raise RuntimeError(f"git config {key} failed: {cfg_proc.stderr.strip()}")

    add_proc = _run_git(["add", "-A"], cwd=root)
    if add_proc.returncode != 0:
        raise RuntimeError(f"git add -A failed in {root}: {add_proc.stderr.strip()}")

    commit_proc = _run_git(
        ["commit", "--allow-empty", "--no-verify", "-q", "-m", commit_message],
        cwd=root,
    )
    if commit_proc.returncode != 0:
        raise RuntimeError(f"git commit failed in {root}: {commit_proc.stderr.strip()}")

    verified = verify_workspace_decontaminated(root)
    if not verified["decontaminated"]:
        raise RuntimeError(f"Workspace failed post-strip decontamination audit: {verified['errors']}")
    return verified


def verify_workspace_decontaminated(repo_dir: str | Path) -> dict[str, Any]:
    """Independently verify ``repo_dir`` contains exactly 1 commit and zero git leak vectors."""
    root = Path(repo_dir).resolve()
    errors: list[str] = []
    if not (root / ".git").exists():
        return {
            "decontaminated": False,
            "git_stripped": False,
            "commit_count": 0,
            "remotes": [],
            "tags": [],
            "branches": [],
            "baseline_head": "",
            "errors": ["Missing .git baseline directory"],
        }

    cnt_proc = _run_git(["rev-list", "--count", "--all"], cwd=root)
    commit_count = int(cnt_proc.stdout.strip()) if cnt_proc.returncode == 0 and cnt_proc.stdout.strip().isdigit() else -1
    if commit_count != 1:
        errors.append(f"Expected exactly 1 commit in decontaminated repo, found {commit_count}")

    rem_proc = _run_git(["remote"], cwd=root)
    remotes = [ln.strip() for ln in rem_proc.stdout.splitlines() if ln.strip()] if rem_proc.returncode == 0 else []
    if remotes:
        errors.append(f"Unexpected git remotes present: {remotes}")

    tag_proc = _run_git(["tag", "-l"], cwd=root)
    tags = [ln.strip() for ln in tag_proc.stdout.splitlines() if ln.strip()] if tag_proc.returncode == 0 else []
    if tags:
        errors.append(f"Unexpected git tags present: {tags}")

    br_proc = _run_git(["branch", "--all", "--format=%(refname:short)"], cwd=root)
    branches = [ln.strip() for ln in br_proc.stdout.splitlines() if ln.strip()] if br_proc.returncode == 0 else []
    if len(branches) != 1:
        errors.append(f"Expected exactly 1 local branch, found {branches}")

    stash_proc = _run_git(["stash", "list"], cwd=root)
    stashes = [ln.strip() for ln in stash_proc.stdout.splitlines() if ln.strip()] if stash_proc.returncode == 0 else []
    if stashes:
        errors.append(f"Unexpected git stash entries present: {len(stashes)}")

    head_proc = _run_git(["rev-parse", "HEAD"], cwd=root)
    baseline_head = head_proc.stdout.strip() if head_proc.returncode == 0 else ""

    return {
        "decontaminated": len(errors) == 0,
        "git_stripped": len(errors) == 0,
        "commit_count": commit_count,
        "remotes": remotes,
        "tags": tags,
        "branches": branches,
        "baseline_head": baseline_head,
        "errors": errors,
    }


def _normalize_patch_rel(raw: str) -> str:
    cleaned = raw.strip().strip('"').replace("\\", "/")
    if cleaned.startswith(("a/", "b/")):
        cleaned = cleaned[2:]
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/")


def extract_patch_paths(patch_text: str) -> tuple[str, ...]:
    """Return sorted unique repository-relative paths modified/created/deleted in ``patch_text``."""
    paths: set[str] = set()
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                for token in (parts[2], parts[3]):
                    if token != "/dev/null":
                        norm = _normalize_patch_rel(token)
                        if norm:
                            paths.add(norm)
        elif line.startswith(("+++ ", "--- ")):
            token = line[4:].split("\t", 1)[0].strip()
            if token and token != "/dev/null":
                norm = _normalize_patch_rel(token)
                if norm:
                    paths.add(norm)
    return tuple(sorted(paths))


def _matches_protected_pattern(rel_posix: str, pattern: str) -> bool:
    pat = pattern.strip().replace("\\", "/").lstrip("./")
    if not pat:
        return False
    norm = rel_posix.replace("\\", "/").lstrip("./")
    name = norm.rsplit("/", 1)[-1]

    if pat.endswith("/**"):
        prefix = pat[:-3].rstrip("/")
        if norm == prefix or norm.startswith(prefix + "/"):
            return True
    if fnmatch.fnmatch(norm, pat):
        return True
    if "/" not in pat and fnmatch.fnmatch(name, pat):
        return True
    return False


def check_protected_paths_in_patch(
    patch_text: str,
    protected_patterns: Sequence[str],
) -> tuple[str, ...]:
    """Return sorted offending paths if ``patch_text`` modifies any protected/test path."""
    if not patch_text.strip() or not protected_patterns:
        return ()
    touched = extract_patch_paths(patch_text)
    offending = [
        rel
        for rel in touched
        if any(_matches_protected_pattern(rel, pat) for pat in protected_patterns)
    ]
    return tuple(sorted(set(offending)))
