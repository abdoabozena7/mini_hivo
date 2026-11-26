"""Official SWE-bench Verified benchmark runner for Mini Hivo's Hybrid Architecture.

Runs a reproducible slice of ``princeton-nlp/SWE-bench_Verified`` tasks through:
  Cloud Thinking Orchestrator (e.g., Groq qwen/qwen3.8-27b)
    + Local Light Worker (e.g., Ollama qwen3.5:2b-q4_K_M, think=False)
and evaluates every generated ``git diff`` inside the official SWE-bench Docker
evaluation container against the hidden ground-truth ``test_patch``
(``FAIL_TO_PASS`` and ``PASS_TO_PASS``).

Disk-safety design (for hosts with tight C: drive space):
  - Pulls ONE official SWE-bench Docker image at a time.
  - Extracts ``/testbed`` onto the repo's workspace drive (e.g. ``output/``).
  - Removes each task's containers and Docker image immediately after evaluation
    unless ``--keep-images`` is specified.

Zero-leakage design:
  - Only ``problem_statement`` and repository files at ``base_commit`` are visible
    to the agent. ``patch``, ``test_patch``, ``FAIL_TO_PASS``, ``PASS_TO_PASS``,
    and ``hints_text`` are NEVER exposed during solving.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tarfile
import time
from typing import Any, Callable
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hivo.hybrid import HybridAgentRunner, HybridRunConfig
from hivo.providers import (
    EndpointConfig,
    cerebras_orchestrator,
    gemini_orchestrator,
    groq_orchestrator,
    load_dotenv,
    nvidia_nim_orchestrator,
    ollama_worker,
    openrouter_orchestrator,
)
from hivo.tools import ToolContext, ToolSpec, err_result, ok_result

DEFAULT_SEED = 42
DEFAULT_SLICE = (
    "psf__requests-1724",
    "pytest-dev__pytest-10051",
    "django__django-16527",
)


def _run_cmd(
    args: list[str],
    *,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
    )


def _swebench_image_name(instance_id: str) -> str:
    return f"swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest"


def fetch_swebench_instances(instance_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch official SWE-bench Verified rows by exact instance_id from HF Datasets Server."""
    wanted = set(instance_ids)
    found: dict[str, dict[str, Any]] = {}
    for offset in range(0, 500, 100):
        if len(found) == len(wanted):
            break
        url = (
            "https://datasets-server.huggingface.co/rows?"
            f"dataset=princeton-nlp/SWE-bench_Verified&config=default&split=test&offset={offset}&length=100"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "MiniHivo/0.5"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("rows", []):
            row = item["row"]
            iid = row.get("instance_id")
            if iid in wanted:
                found[iid] = row
    missing = [iid for iid in instance_ids if iid not in found]
    if missing:
        raise ValueError(f"SWE-bench Verified instance(s) not found: {missing}")
    return [found[iid] for iid in instance_ids]


def _extract_test_files(test_patch: str) -> list[str]:
    files: list[str] = []
    for line in test_patch.splitlines():
        if line.startswith("+++ b/"):
            rel = line[6:].strip()
            if rel and rel != "/dev/null" and rel not in files:
                files.append(rel)
    return files


def _django_test_modules(test_files: list[str]) -> list[str]:
    modules: list[str] = []
    for rel in test_files:
        cleaned = rel.replace("\\", "/")
        if cleaned.startswith("tests/"):
            cleaned = cleaned[len("tests/") :]
        if cleaned.endswith(".py"):
            cleaned = cleaned[:-3]
        mod = cleaned.replace("/", ".")
        if mod and mod not in modules:
            modules.append(mod)
    return modules


def _official_eval_command(repo: str, test_patch: str) -> str:
    test_files = _extract_test_files(test_patch)
    if repo == "django/django":
        mods = " ".join(_django_test_modules(test_files))
        return f"./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 {mods}"
    files_arg = " ".join(test_files)
    return f"pytest -rA --tb=short {files_arg}"


def _parse_pytest_statuses(output: str) -> dict[str, str]:
    """Parse pytest -rA short summary lines into {test_id: PASSED|FAILED|ERROR|SKIPPED}."""
    statuses: dict[str, str] = {}
    pat = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)\s+(\S+)")
    for raw_line in output.splitlines():
        line = raw_line.strip()
        m = pat.match(line)
        if m:
            statuses[m.group(2)] = m.group(1)
    return statuses


def _parse_django_unittest_statuses(output: str) -> dict[str, str]:
    """Parse Django runtests.py --verbosity 2 lines into {test_label: PASSED|FAILED|ERROR|SKIPPED}."""
    statuses: dict[str, str] = {}
    pat = re.compile(r"^(.+?)\s+\.\.\.\s+(ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)\s*$")
    for raw_line in output.splitlines():
        line = raw_line.strip()
        m = pat.match(line)
        if not m:
            continue
        label = m.group(1).strip()
        outcome = m.group(2).strip()
        if outcome == "ok":
            statuses[label] = "PASSED"
        elif outcome == "FAIL":
            statuses[label] = "FAILED"
        elif outcome == "ERROR":
            statuses[label] = "ERROR"
        else:
            statuses[label] = outcome.upper()
    return statuses


def _check_test_targets(
    repo: str,
    output: str,
    fail_to_pass: list[str],
    pass_to_pass: list[str],
) -> dict[str, Any]:
    parsed = (
        _parse_django_unittest_statuses(output)
        if repo == "django/django"
        else _parse_pytest_statuses(output)
    )

    def _lookup(test_id: str) -> str:
        if test_id in parsed:
            return parsed[test_id]
        # Handle Django method-only match when Python 3.11+ prints full qualname or vice versa.
        head = test_id.split(" ", 1)[0]
        for k, v in parsed.items():
            if k == test_id or k.startswith(head + " ") or k.endswith(test_id):
                return v
        return "MISSING"

    f2p_results = {tid: _lookup(tid) for tid in fail_to_pass}
    p2p_results = {tid: _lookup(tid) for tid in pass_to_pass}
    f2p_passed = sum(1 for v in f2p_results.values() if v == "PASSED")
    p2p_passed = sum(1 for v in p2p_results.values() if v == "PASSED")
    return {
        "f2p_passed": f2p_passed,
        "f2p_total": len(fail_to_pass),
        "p2p_passed": p2p_passed,
        "p2p_total": len(pass_to_pass),
        "f2p_all_passed": len(fail_to_pass) > 0 and f2p_passed == len(fail_to_pass),
        "p2p_all_passed": p2p_passed == len(pass_to_pass),
        "f2p_details": f2p_results,
        "p2p_failed": {k: v for k, v in p2p_results.items() if v != "PASSED"},
    }


_CONDA_ACTIVATE = (
    'if [ -f /opt/miniconda3/etc/profile.d/conda.sh ]; then '
    'source /opt/miniconda3/etc/profile.d/conda.sh; '
    'elif [ -f /opt/conda/etc/profile.d/conda.sh ]; then '
    'source /opt/conda/etc/profile.d/conda.sh; '
    'else echo "CONDA_NOT_FOUND" >&2; exit 127; fi && '
    'conda activate testbed'
)


def _docker_eval_once(
    image: str,
    *,
    repo: str,
    eval_cmd: str,
    model_patch: str,
    test_patch: str,
    timeout_sec: int = 300,
) -> dict[str, Any]:
    """Run an isolated official Docker evaluation container applying model_patch + test_patch."""
    cid = ""
    try:
        create_proc = _run_cmd(["docker", "run", "-d", image, "sleep", "900"], timeout=60)
        if create_proc.returncode != 0:
            return {
                "infra_ok": False,
                "error": create_proc.stderr.decode("utf-8", errors="replace").strip(),
            }
        cid = create_proc.stdout.decode("utf-8", errors="replace").strip()

        def _exec_bash(script: str, *, stdin_bytes: bytes | None = None, to: int = timeout_sec) -> tuple[int, str, str]:
            proc = _run_cmd(
                ["docker", "exec", "-i", cid, "bash", "-lc", script],
                input_bytes=stdin_bytes,
                timeout=to,
            )
            return (
                proc.returncode,
                proc.stdout.decode("utf-8", errors="replace"),
                proc.stderr.decode("utf-8", errors="replace"),
            )

        patch_applied = True
        patch_apply_err = ""
        if model_patch.strip():
            rc, out, err = _exec_bash(
                "cd /testbed && git apply -v -",
                stdin_bytes=model_patch.encode("utf-8"),
                to=60,
            )
            if rc != 0:
                patch_applied = False
                patch_apply_err = (err or out)[:1000]

        test_patch_applied = True
        if test_patch.strip():
            rc_t, out_t, err_t = _exec_bash(
                "cd /testbed && git apply -v -",
                stdin_bytes=test_patch.encode("utf-8"),
                to=60,
            )
            if rc_t != 0:
                test_patch_applied = False
                patch_apply_err += f" | test_patch apply failed: {(err_t or out_t)[:500]}"

        test_script = f"{_CONDA_ACTIVATE} && cd /testbed && {eval_cmd}"
        rc_run, out_run, err_run = _exec_bash(test_script, to=timeout_sec)
        combined = out_run + "\n" + err_run
        return {
            "infra_ok": True,
            "patch_applied": patch_applied,
            "test_patch_applied": test_patch_applied,
            "patch_apply_error": patch_apply_err,
            "exit_code": rc_run,
            "output": combined,
        }
    except subprocess.TimeoutExpired:
        return {"infra_ok": False, "error": f"Docker eval timed out after {timeout_sec}s"}
    finally:
        if cid:
            _run_cmd(["docker", "rm", "-f", cid], timeout=30)


def _extract_testbed_to_host(image: str, dest_repo: Path) -> None:
    """Copy /testbed from the official Docker image onto the host workspace cleanly.

    Uses ``docker cp <cid>:/testbed/. -`` + Python ``tarfile`` so Linux symlinks
    (e.g. in Django docs) become Git-compatible plain-text link stubs under
    ``core.symlinks=false`` instead of failing on Windows without symlink privilege.
    """
    dest_repo.mkdir(parents=True, exist_ok=True)
    create_proc = _run_cmd(["docker", "create", image], timeout=60)
    if create_proc.returncode != 0:
        raise RuntimeError(
            f"docker create failed for {image}: {create_proc.stderr.decode('utf-8', errors='replace')}"
        )
    cid = create_proc.stdout.decode("utf-8", errors="replace").strip()
    try:
        proc = subprocess.Popen(
            ["docker", "cp", f"{cid}:/testbed/.", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.stdout is not None
        root_resolved = dest_repo.resolve()
        with tarfile.open(fileobj=proc.stdout, mode="r|*") as tf:
            for member in tf:
                rel = member.name.replace("\\", "/")
                while rel.startswith("./"):
                    rel = rel[2:]
                rel = rel.lstrip("/")
                if not rel or rel == ".":
                    continue
                target = (root_resolved / rel).resolve()
                if not target.is_relative_to(root_resolved):
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.issym():
                    # Under Git on Windows (core.symlinks=false), symlinks are stored as text files containing linkname.
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(member.linkname.encode("utf-8"))
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = tf.extractfile(member)
                    if src is not None:
                        with target.open("wb") as out_fh:
                            shutil.copyfileobj(src, out_fh)
        _, err_bytes = proc.communicate(timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(
                f"docker cp stream failed for {image}: {err_bytes.decode('utf-8', errors='replace')}"
            )
    finally:
        _run_cmd(["docker", "rm", "-f", cid], timeout=30)
    if not (dest_repo / ".git").exists():
        raise RuntimeError(f"Extracted /testbed is missing .git directory at {dest_repo}")
    # Prevent Windows NTFS filemode/symlink/autocrlf ghost diffs against Linux /testbed
    _run_cmd(["git", "config", "core.filemode", "false"], cwd=dest_repo, timeout=30)
    _run_cmd(["git", "config", "core.symlinks", "false"], cwd=dest_repo, timeout=30)
    _run_cmd(["git", "config", "core.autocrlf", "false"], cwd=dest_repo, timeout=30)


def _git_diff_workspace(repo_dir: Path) -> str:
    proc = _run_cmd(
        ["git", "-c", "core.filemode=false", "diff", "--no-color"],
        cwd=repo_dir,
        timeout=60,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", errors="replace")


def _make_container_test_tool(
    image: str,
    repo_dir: Path,
    repo_name: str,
) -> tuple[ToolSpec, Callable[[], None]]:
    """Create a sandboxed orchestrator tool that runs existing repo tests in Docker.

    Never applies or accesses hidden benchmark ``test_patch``. Syncs only the
    current workspace ``git diff`` into a clean reset of ``/testbed`` before
    running the requested test command inside ``conda activate testbed``.
    """
    state: dict[str, str] = {"cid": ""}

    def _ensure_container() -> str:
        if state["cid"]:
            return state["cid"]
        proc = _run_cmd(["docker", "run", "-d", image, "sleep", "1800"], timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())
        state["cid"] = proc.stdout.decode("utf-8", errors="replace").strip()
        return state["cid"]

    def cleanup() -> None:
        if state["cid"]:
            _run_cmd(["docker", "rm", "-f", state["cid"]], timeout=30)
            state["cid"] = ""

    def _handle_run_repo_tests(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        target = str(args.get("test_target") or "").strip()
        k_expr = str(args.get("k_filter") or "").strip()
        if any(tok in target + k_expr for tok in (";", "&&", "||", "|", "`", "$(" , "\n", "\r")):
            return err_result(
                "Shell operators are not allowed in test_target or k_filter.",
                hint="Pass a clean test file/module path (e.g. 'testing/logging/test_fixture.py') and optional pytest -k pattern.",
            )
        try:
            cid = _ensure_container()
        except Exception as exc:
            return err_result(f"Failed to start test container: {exc}", hint="Inspect code statically with read_file.")

        # Reset /testbed cleanly to base_commit and apply current workspace diff
        diff_text = _git_diff_workspace(repo_dir)
        reset_proc = _run_cmd(
            ["docker", "exec", "-i", cid, "bash", "-lc", "cd /testbed && git checkout -- . && git clean -fd"],
            timeout=60,
        )
        if reset_proc.returncode != 0:
            return err_result("Failed to reset container /testbed.", hint="Retry run_repo_tests.")
        if diff_text.strip():
            apply_proc = _run_cmd(
                ["docker", "exec", "-i", cid, "bash", "-lc", "cd /testbed && git apply -"],
                input_bytes=diff_text.encode("utf-8"),
                timeout=60,
            )
            if apply_proc.returncode != 0:
                err_txt = apply_proc.stderr.decode("utf-8", errors="replace")[:400]
                return err_result(
                    f"Current workspace diff failed to apply inside container: {err_txt}",
                    hint="Inspect your diff with run_command('git diff') and verify line endings.",
                )

        if repo_name == "django/django":
            t_arg = target or "admin_views"
            cmd = f"./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 {t_arg}"
            if k_expr:
                cmd += f" -k {json.dumps(k_expr)}"
        else:
            cmd = f"pytest -q --tb=short {target}"
            if k_expr:
                cmd += f" -k {json.dumps(k_expr)}"

        script = f"{_CONDA_ACTIVATE} && cd /testbed && {cmd}"
        try:
            proc = _run_cmd(["docker", "exec", "-i", cid, "bash", "-lc", script], timeout=120)
        except subprocess.TimeoutExpired:
            return err_result(
                "Container test command timed out after 120s.",
                hint="Narrow test_target or k_filter to a single test file or test case.",
            )

        out = proc.stdout.decode("utf-8", errors="replace")
        err = proc.stderr.decode("utf-8", errors="replace")
        combined = (out + ("\n" + err if err.strip() else "")).strip()
        truncated = False
        if len(combined) > 3500:
            combined = combined[:1400] + "\n... [truncated] ...\n" + combined[-1800:]
            truncated = True
        return ok_result(
            {
                "command": cmd,
                "exit_code": proc.returncode,
                "output": combined,
            },
            truncated=truncated,
        )

    spec = ToolSpec(
        name="run_repo_tests",
        description=(
            "Run existing repository tests inside the task's isolated Linux test environment "
            "against your current workspace edits. Pass a focused test file or Django test module "
            "in test_target (and optional k_filter substring)."
        ),
        effect="exec",
        model_tier="orchestrator_only",
        parameters={
            "type": "object",
            "properties": {
                "test_target": {
                    "type": "string",
                    "description": "Focused test file path (pytest) or dotted test module (Django runtests.py).",
                },
                "k_filter": {
                    "type": "string",
                    "default": "",
                    "description": "Optional -k test name filter to keep runs fast.",
                },
            },
            "required": ["test_target"],
            "additionalProperties": False,
        },
        handler=_handle_run_repo_tests,
    )
    return spec, cleanup


def _build_cloud_config(provider: str, model_override: str | None) -> EndpointConfig:
    p = provider.strip().lower()
    if p == "groq":
        return groq_orchestrator(model=model_override or "qwen/qwen3.8-27b", max_tokens=1536)
    if p == "nvidia":
        return nvidia_nim_orchestrator(model=model_override or "z-ai/glm-5.3-flash", max_tokens=2048)
    if p == "openrouter":
        return openrouter_orchestrator(model=model_override or "qwen/qwen3.8-27b", max_tokens=2048)
    if p == "cerebras":
        return cerebras_orchestrator(model=model_override or "qwen-3.8-27b", max_tokens=2048)
    if p == "gemini":
        return gemini_orchestrator(model=model_override or "gemini-3-flash-preview", max_tokens=2048)
    raise ValueError(f"Unsupported provider {provider!r}")


def _build_task_prompt(row: dict[str, Any]) -> str:
    repo = row["repo"]
    problem = str(row["problem_statement"]).strip()
    if len(problem) > 2400:
        problem = problem[:2400] + "\n... [problem statement truncated for ITPM context budget]"
    test_tip = (
        "You can run focused tests inside the repo's Linux environment via `run_repo_tests(test_target=..., k_filter=...)` "
        "(for Django, use a dotted module like `admin_views.test_templatetags`)."
        if repo == "django/django"
        else "You can run focused tests inside the repo's Linux environment via `run_repo_tests(test_target=..., k_filter=...)`."
    )
    return (
        f"Repository: `{repo}`\n"
        f"Fix the GitHub issue below with a minimal surgical patch.\n"
        f"Workflow: locate the exact buggy lines with `search_code`/`code_intel`/`read_file` -> "
        f"delegate the edit via `dispatch_worker` (give exact file path, line numbers, and exact code change in `context`) -> "
        f"verify with `run_repo_tests` and `run_command('git diff')` -> reply with concise summary.\n"
        f"{test_tip}\n"
        f"Do NOT edit test files.\n\n"
        f"ISSUE:\n{problem}"
    )


def run_single_instance(
    row: dict[str, Any],
    *,
    run_dir: Path,
    orch_cfg: EndpointConfig,
    worker_cfg: EndpointConfig,
    keep_images: bool,
    max_orch_turns: int,
    max_worker_turns: int,
    max_elapsed_sec: float,
) -> dict[str, Any]:
    iid = row["instance_id"]
    repo = row["repo"]
    image = _swebench_image_name(iid)
    fail_to_pass = (
        json.loads(row["FAIL_TO_PASS"]) if isinstance(row["FAIL_TO_PASS"], str) else list(row["FAIL_TO_PASS"])
    )
    pass_to_pass = (
        json.loads(row["PASS_TO_PASS"]) if isinstance(row["PASS_TO_PASS"], str) else list(row["PASS_TO_PASS"])
    )
    test_patch = str(row["test_patch"])
    eval_cmd = _official_eval_command(repo, test_patch)

    task_dir = run_dir / iid
    repo_dir = task_dir / "repo"
    scratch_dir = task_dir / "scratch"
    patches_dir = run_dir / "patches"
    patches_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n============================================================", flush=True)
    print(f"[TASK] {iid} ({repo}, difficulty={row.get('difficulty')})", flush=True)
    print(f"[IMAGE] Pulling {image} ...", flush=True)
    t_task = time.perf_counter()

    pull_proc = _run_cmd(["docker", "pull", image], timeout=600)
    if pull_proc.returncode != 0:
        err = pull_proc.stderr.decode("utf-8", errors="replace").strip()
        print(f"[PULL FAILED] {err[:300]}", flush=True)
        return {
            "instance_id": iid,
            "repo": repo,
            "difficulty": row.get("difficulty"),
            "status": "docker_pull_failed",
            "resolved": False,
            "error": err[:500],
        }

    test_tool_cleanup = None
    try:
        # Pre-solve container sanity check: verify conda testbed activates BEFORE spending LLM tokens
        env_check = _run_cmd(
            ["docker", "run", "--rm", image, "bash", "-lc", f"{_CONDA_ACTIVATE} && which python && python --version"],
            timeout=60,
        )
        if env_check.returncode != 0:
            err = (env_check.stderr or env_check.stdout).decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Container conda testbed check failed: {err[:400]}")
        print(
            f"[ENV OK] {env_check.stdout.decode('utf-8', errors='replace').strip().replace(chr(10), ' | ')}",
            flush=True,
        )

        print(f"[WORKSPACE] Extracting /testbed -> {repo_dir}", flush=True)
        _extract_testbed_to_host(image, repo_dir)

        test_tool_spec, test_tool_cleanup = _make_container_test_tool(image, repo_dir, repo)
        protected = ("tests/**", "testing/**", "test_*.py", "*_test.py")

        def on_event(name: str, data: dict[str, Any]) -> None:
            print(f"  [{iid}] {name}: {data}", flush=True)

        runner = HybridAgentRunner(
            repo_dir,
            HybridRunConfig(
                orchestrator=orch_cfg,
                worker=worker_cfg,
                include_run_command=True,
                allowed_commands=("git",),
                protected_paths=protected,
                extra_orchestrator_tools=(test_tool_spec,),
                orchestrator_max_read_lines=80,
                orchestrator_max_output_chars=4_000,
                worker_max_read_lines=100,
                max_orchestrator_turns=max_orch_turns,
                max_worker_turns=max_worker_turns,
                max_worker_dispatches=4,
                max_history_chars=8_500,
                worker_max_history_chars=7_500,
                max_elapsed_sec=max_elapsed_sec,
                auto_checkpoint_worker=True,
            ),
            event_callback=on_event,
            scratch_dir=scratch_dir,
        )

        print(f"[SOLVE] Running HybridAgentRunner ({orch_cfg.model} -> {worker_cfg.model}) ...", flush=True)
        agent_res = runner.run(_build_task_prompt(row))
        model_patch = _git_diff_workspace(repo_dir)
        patch_file = patches_dir / f"{iid}.diff"
        patch_file.write_text(model_patch, encoding="utf-8")

        if test_tool_cleanup is not None:
            test_tool_cleanup()
            test_tool_cleanup = None

        print(
            f"[AGENT DONE] status={agent_res.status} | patch_bytes={len(model_patch)} | "
            f"orch_turns={agent_res.orchestrator_turns} | worker_dispatches={len(agent_res.worker_runs)} | "
            f"orch_tokens={agent_res.orchestrator_usage.total_tokens} | worker_tokens={agent_res.worker_usage.total_tokens} | "
            f"elapsed={agent_res.elapsed_ms / 1000:.1f}s",
            flush=True,
        )

        # Independent Official Docker Oracle Evaluation
        print(f"[ORACLE 1/2] Baseline check (test_patch only, no fix) ...", flush=True)
        base_eval = _docker_eval_once(
            image,
            repo=repo,
            eval_cmd=eval_cmd,
            model_patch="",
            test_patch=test_patch,
        )
        base_check = (
            _check_test_targets(repo, base_eval.get("output", ""), fail_to_pass, pass_to_pass)
            if base_eval.get("infra_ok")
            else {"f2p_passed": 0, "f2p_total": len(fail_to_pass), "f2p_all_passed": False}
        )
        print(
            f"  baseline F2P={base_check['f2p_passed']}/{base_check['f2p_total']} | "
            f"P2P={base_check.get('p2p_passed', 0)}/{base_check.get('p2p_total', len(pass_to_pass))} "
            f"(expected F2P < {base_check['f2p_total']})",
            flush=True,
        )
        (task_dir / "oracle_baseline.log").write_text(base_eval.get("output", ""), encoding="utf-8")

        print(f"[ORACLE 2/2] Candidate eval (model_patch + official test_patch) ...", flush=True)
        cand_eval = _docker_eval_once(
            image,
            repo=repo,
            eval_cmd=eval_cmd,
            model_patch=model_patch,
            test_patch=test_patch,
        )
        cand_check = (
            _check_test_targets(repo, cand_eval.get("output", ""), fail_to_pass, pass_to_pass)
            if cand_eval.get("infra_ok")
            else {
                "f2p_passed": 0,
                "f2p_total": len(fail_to_pass),
                "p2p_passed": 0,
                "p2p_total": len(pass_to_pass),
                "f2p_all_passed": False,
                "p2p_all_passed": False,
            }
        )
        (task_dir / "oracle_eval.log").write_text(cand_eval.get("output", ""), encoding="utf-8")

        resolved = bool(
            model_patch.strip()
            and cand_eval.get("infra_ok")
            and cand_eval.get("patch_applied")
            and cand_eval.get("test_patch_applied")
            and cand_check.get("f2p_all_passed")
            and cand_check.get("p2p_all_passed")
        )
        print(
            f"[VERDICT] {iid}: resolved={resolved} | "
            f"F2P={cand_check['f2p_passed']}/{cand_check['f2p_total']} | "
            f"P2P={cand_check['p2p_passed']}/{cand_check['p2p_total']}",
            flush=True,
        )

        record = {
            "instance_id": iid,
            "repo": repo,
            "version": row.get("version"),
            "difficulty": row.get("difficulty"),
            "base_commit": row.get("base_commit"),
            "image": image,
            "eval_command": eval_cmd,
            "agent_status": agent_res.status,
            "agent_error": agent_res.error,
            "orchestrator_model": agent_res.orchestrator_model,
            "worker_model": agent_res.worker_model,
            "orchestrator_turns": agent_res.orchestrator_turns,
            "orchestrator_tool_calls": agent_res.orchestrator_tool_calls,
            "orchestrator_reasoning_chars": agent_res.orchestrator_reasoning_chars,
            "orchestrator_usage": agent_res.orchestrator_usage.to_dict(),
            "worker_dispatches": len(agent_res.worker_runs),
            "worker_rollbacks": sum(1 for w in agent_res.worker_runs if w.rolled_back),
            "worker_usage": agent_res.worker_usage.to_dict(),
            "agent_elapsed_sec": round(agent_res.elapsed_ms / 1000.0, 2),
            "total_task_elapsed_sec": round(time.perf_counter() - t_task, 2),
            "patch_bytes": len(model_patch),
            "patch_file": str(patch_file.relative_to(run_dir)),
            "baseline_f2p_passed": base_check["f2p_passed"],
            "baseline_f2p_total": base_check["f2p_total"],
            "baseline_oracle_valid": base_check["f2p_passed"] < base_check["f2p_total"],
            "patch_applied": bool(cand_eval.get("patch_applied")),
            "f2p_passed": cand_check["f2p_passed"],
            "f2p_total": cand_check["f2p_total"],
            "p2p_passed": cand_check["p2p_passed"],
            "p2p_total": cand_check["p2p_total"],
            "f2p_details": cand_check.get("f2p_details", {}),
            "p2p_failed": cand_check.get("p2p_failed", {}),
            "resolved": resolved,
        }
        (task_dir / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record
    finally:
        if test_tool_cleanup is not None:
            test_tool_cleanup()
        if not keep_images:
            print(f"[CLEANUP] Removing Docker image {image} to preserve C: free space ...", flush=True)
            _run_cmd(["docker", "rmi", "-f", image], timeout=120)
        # Clean extracted repo copy to keep disk tidy (patch + logs are preserved)
        if repo_dir.exists():
            shutil.rmtree(repo_dir, ignore_errors=True)


def main() -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description="Run SWE-bench Verified slice on Mini Hivo Hybrid Runner.")
    parser.add_argument(
        "--provider",
        choices=("groq", "nvidia", "openrouter", "cerebras", "gemini"),
        default="groq",
    )
    parser.add_argument("--model", default=None, help="Cloud orchestrator model ID override.")
    parser.add_argument("--worker-model", default="qwen3.5:2b-q4_K_M", help="Local Ollama worker model.")
    parser.add_argument("--worker-ctx", type=int, default=4096, help="Local worker num_ctx cap.")
    parser.add_argument(
        "--instances",
        nargs="+",
        default=list(DEFAULT_SLICE),
        help="Explicit SWE-bench Verified instance IDs (default: seed=42 3-task stratified slice).",
    )
    parser.add_argument("--max-orch-turns", type=int, default=14)
    parser.add_argument("--max-worker-turns", type=int, default=5)
    parser.add_argument("--max-elapsed-sec", type=float, default=420.0)
    parser.add_argument("--keep-images", action="store_true", help="Do not docker rmi task images after eval.")
    parser.add_argument("--output-dir", default=None, help="Optional explicit run output directory.")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else (REPO_ROOT / "output" / "swebench_hybrid" / f"run_{stamp}").resolve()
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    orch_cfg = _build_cloud_config(args.provider, args.model)
    worker_cfg = ollama_worker(model=args.worker_model, num_ctx=args.worker_ctx, think=False)

    print(f"[RUN DIR] {run_dir}", flush=True)
    print(f"[ORCHESTRATOR] {orch_cfg.base_url} | {orch_cfg.model} | think={orch_cfg.think} | effort={orch_cfg.reasoning_effort}", flush=True)
    print(f"[WORKER] {worker_cfg.base_url} | {worker_cfg.model} | num_ctx={worker_cfg.num_ctx} | think={worker_cfg.think}", flush=True)
    print(f"[INSTANCES (seed={DEFAULT_SEED})] {args.instances}", flush=True)

    rows = fetch_swebench_instances(args.instances)
    results: list[dict[str, Any]] = []
    predictions_path = run_dir / "predictions.jsonl"

    for row in rows:
        rec = run_single_instance(
            row,
            run_dir=run_dir,
            orch_cfg=orch_cfg,
            worker_cfg=worker_cfg,
            keep_images=args.keep_images,
            max_orch_turns=args.max_orch_turns,
            max_worker_turns=args.max_worker_turns,
            max_elapsed_sec=args.max_elapsed_sec,
        )
        results.append(rec)
        # Append prediction incrementally so progress is never lost
        patch_rel = rec.get("patch_file")
        patch_txt = (run_dir / patch_rel).read_text(encoding="utf-8") if patch_rel and (run_dir / patch_rel).is_file() else ""
        with predictions_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "instance_id": rec["instance_id"],
                "model_name_or_path": f"{orch_cfg.model}+{worker_cfg.model}",
                "model_patch": patch_txt,
            }) + "\n")
        (run_dir / "results.json").write_text(
            json.dumps(
                {
                    "seed": DEFAULT_SEED,
                    "orchestrator": orch_cfg.to_dict(),
                    "worker": worker_cfg.to_dict(),
                    "n_tasks": len(results),
                    "resolved_count": sum(1 for r in results if r.get("resolved")),
                    "results": results,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    resolved_n = sum(1 for r in results if r.get("resolved"))
    print(f"\n================ SUMMARY (N={len(results)}) ================", flush=True)
    print(f"Resolved: {resolved_n}/{len(results)}", flush=True)
    for r in results:
        print(
            f"  {r['instance_id']:28s} | resolved={str(r.get('resolved')):5s} | "
            f"F2P={r.get('f2p_passed', 0)}/{r.get('f2p_total', 0)} | "
            f"P2P={r.get('p2p_passed', 0)}/{r.get('p2p_total', 0)} | "
            f"status={r.get('agent_status')} | orch_tok={((r.get('orchestrator_usage') or {}).get('total_tokens'))} | "
            f"worker_tok={((r.get('worker_usage') or {}).get('total_tokens'))}",
            flush=True,
        )
    print(f"Saved full results to: {run_dir / 'results.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
