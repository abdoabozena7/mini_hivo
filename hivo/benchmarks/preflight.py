"""Zero-LLM Host & Sandbox Preflight Checker for Mini Hivo live benchmarks.

Verifies local machine readiness before spending any LLM tokens:
  1. Docker daemon reachable + ``--network none`` driver available.
  2. Host disk headroom on both the workspace drive and Docker/system drive.
  3. Provider API credential present via process env or gitignored ``.env`` (ZERO secret printing).
  4. Local Ollama worker pulled & empirical GPU residency check (catching silent CPU spill).
  5. Optional suite CLI availability (e.g., ``harbor`` for Terminal-Bench 4.1).

Usage:
    python -m hivo.benchmarks.preflight --provider nvidia --worker-model qwen3.5:2b-q4_K_M
    python -m hivo.benchmarks.preflight --provider groq --skip-local-worker --json
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request

from hivo.providers.env import load_dotenv
from hivo.providers.types import DEFAULT_OLLAMA_BASE_URL

PROVIDER_ENV_VARS: dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    required: bool
    ok: bool
    detail: str
    hint: str = ""


CmdRunner = Callable[[list[str], int], tuple[int, str, str]]
HttpJsonGetter = Callable[[str, float], dict[str, Any]]
DiskUsageGetter = Callable[[Path], tuple[int, int, int]]
WhichGetter = Callable[[str], str | None]


def _default_cmd_runner(args: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"Executable not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"Command timed out after {timeout}s"


def _default_http_json_getter(url: str, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "MiniHivo-Preflight/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _default_disk_usage(path: Path) -> tuple[int, int, int]:
    usage = shutil.disk_usage(str(path))
    return usage.total, usage.used, usage.free


def _check_docker(cmd_runner: CmdRunner, *, required: bool) -> PreflightCheck:
    rc, out, err = cmd_runner(["docker", "info", "--format", "{{.ServerVersion}}"], 15)
    if rc != 0 or not out:
        return PreflightCheck(
            name="docker_sandbox",
            required=required,
            ok=False,
            detail=f"Docker daemon unreachable: {(err or out)[:180]}",
            hint="Start Docker Desktop / dockerd and verify `docker info` exits 0 before running containerized benchmarks.",
        )
    net_rc, net_out, net_err = cmd_runner(
        ["docker", "network", "ls", "--filter", "name=^none$", "--format", "{{.Name}}"],
        15,
    )
    has_none = net_rc == 0 and any(ln.strip() == "none" for ln in net_out.splitlines())
    if not has_none:
        return PreflightCheck(
            name="docker_sandbox",
            required=required,
            ok=False,
            detail=f"Docker {out} reachable, but `--network none` driver check failed: {net_err[:140]}",
            hint="Ensure Docker's built-in `none` network is available for sealed decontamination runs.",
        )
    return PreflightCheck(
        name="docker_sandbox",
        required=required,
        ok=True,
        detail=f"Docker {out} active; `--network none` isolation driver verified.",
    )


def _check_disk(
    workspace_dir: Path,
    min_free_gb: float,
    disk_usage: DiskUsageGetter,
) -> PreflightCheck:
    checked_roots: list[Path] = []
    ws_anchor = Path(workspace_dir.resolve().anchor or str(workspace_dir.resolve()))
    checked_roots.append(ws_anchor)
    sys_anchor = Path("C:\\") if os.name == "nt" else Path("/")
    if sys_anchor not in checked_roots and sys_anchor.exists():
        checked_roots.append(sys_anchor)

    parts: list[str] = []
    low: list[str] = []
    for root in checked_roots:
        try:
            _total, _used, free = disk_usage(root)
            free_gb = free / (1024 ** 3)
            label = str(root).rstrip("\\/") or "/"
            parts.append(f"{label}={free_gb:.1f} GB free")
            if free_gb < min_free_gb:
                low.append(f"{label} ({free_gb:.1f} GB < {min_free_gb:.1f} GB)")
        except OSError as exc:
            low.append(f"{root}: {exc}")

    if low:
        return PreflightCheck(
            name="disk_headroom",
            required=True,
            ok=False,
            detail="; ".join(parts) if parts else "; ".join(low),
            hint=f"Free space below {min_free_gb:.1f} GB threshold on {', '.join(low)}. Prune unused Docker images (`docker image prune`) or clear `output/`.",
        )
    return PreflightCheck(
        name="disk_headroom",
        required=True,
        ok=True,
        detail="; ".join(parts) + f" (threshold >= {min_free_gb:.1f} GB).",
    )


def _check_provider_key(
    provider: str,
    dotenv_path: Path,
    env: Mapping[str, str],
) -> PreflightCheck:
    key_name = PROVIDER_ENV_VARS.get(provider.strip().lower())
    if not key_name:
        return PreflightCheck(
            name="provider_credentials",
            required=True,
            ok=False,
            detail=f"Unsupported provider {provider!r}.",
            hint=f"Use one of: {', '.join(sorted(PROVIDER_ENV_VARS))}.",
        )
    present = bool(str(env.get(key_name) or "").strip())
    if not present and dotenv_path.is_file():
        loaded = load_dotenv(dotenv_path, override=False)
        present = bool(str(loaded.get(key_name) or "").strip())
    if not present:
        return PreflightCheck(
            name="provider_credentials",
            required=True,
            ok=False,
            detail=f"Environment variable `{key_name}` is unset or empty (provider={provider}).",
            hint=f"Set `{key_name}` in your local gitignored `.env` or shell environment (never commit `.env`).",
        )
    # Never print or return the key value or prefix.
    return PreflightCheck(
        name="provider_credentials",
        required=True,
        ok=True,
        detail=f"`{key_name}` resolved cleanly for provider `{provider}` (value redacted).",
    )


def _check_local_worker(
    worker_model: str,
    ollama_base_url: str,
    http_get: HttpJsonGetter,
    cmd_runner: CmdRunner,
    *,
    required: bool,
) -> tuple[PreflightCheck, float | None]:
    base = ollama_base_url.rstrip("/")
    try:
        tags_data = http_get(f"{base}/api/tags", 5.0)
    except Exception as exc:
        return (
            PreflightCheck(
                name="local_worker_ollama",
                required=required,
                ok=False,
                detail=f"Ollama unreachable at {base}: {exc}",
                hint="Start Ollama (`ollama serve`) or pass `--skip-local-worker` for orchestrator-only runs.",
            ),
            None,
        )

    models = [str(m.get("name") or "") for m in (tags_data.get("models") or []) if isinstance(m, Mapping)]
    wanted_norm = worker_model.strip()
    pulled = any(
        m == wanted_norm or (":" not in wanted_norm and m.startswith(wanted_norm + ":"))
        for m in models
    )
    if not pulled:
        return (
            PreflightCheck(
                name="local_worker_ollama",
                required=required,
                ok=False,
                detail=f"Ollama reachable, but worker model `{wanted_norm}` is not pulled.",
                hint=f"Run `ollama pull {wanted_norm}` before benchmarking the local-worker arm.",
            ),
            None,
        )

    residency_pct: float | None = None
    ps_note = "not currently loaded in VRAM (will load on first call)"
    try:
        ps_data = http_get(f"{base}/api/ps", 5.0)
        for item in ps_data.get("models") or []:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or "")
            if name == wanted_norm or name.startswith(wanted_norm):
                size = int(item.get("size") or 0)
                size_vram = int(item.get("size_vram") or 0)
                if size > 0:
                    residency_pct = round(100.0 * size_vram / size, 1)
                    ps_note = f"loaded ({size_vram / (1024**3):.2f}/{size / (1024**3):.2f} GB VRAM, {residency_pct}% GPU)"
                break
    except Exception:
        pass

    gpu_note = ""
    nv_rc, nv_out, _ = cmd_runner(
        ["nvidia-smi", "--query-gpu=name,memory.free,memory.total", "--format=csv,noheader"],
        10,
    )
    if nv_rc == 0 and nv_out:
        gpu_note = f" | GPU: {nv_out.splitlines()[0].strip()}"

    if residency_pct is not None and residency_pct < 99.0:
        return (
            PreflightCheck(
                name="local_worker_ollama",
                required=required,
                ok=False,
                detail=f"Model `{wanted_norm}` shows CPU spill: {ps_note}{gpu_note}.",
                hint="Enable `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, or use a smaller quant (`Q4_K_M`) / lower `num_ctx` for 100% GPU residency.",
            ),
            residency_pct,
        )

    return (
        PreflightCheck(
            name="local_worker_ollama",
            required=required,
            ok=True,
            detail=f"Model `{wanted_norm}` pulled; {ps_note}{gpu_note}.",
        ),
        residency_pct,
    )


def _check_harbor(which_fn: WhichGetter, *, required: bool) -> PreflightCheck:
    found = which_fn("harbor")
    if found:
        return PreflightCheck(
            name="harbor_cli",
            required=required,
            ok=True,
            detail="Harbor CLI detected on PATH (ready for Terminal-Bench 4.1).",
        )
    return PreflightCheck(
        name="harbor_cli",
        required=required,
        ok=not required,
        detail="Harbor CLI not installed on PATH" + (" (required for Terminal-Bench 4.1)." if required else " (optional until Terminal-Bench 4.1 runs)."),
        hint="Install Harbor when ready to run Stage 1 Terminal-Bench 4.1 (`uv tool install harbor` or `pip install harbor`).",
    )


def run_preflight(
    *,
    repo_root: Path,
    provider: str = "groq",
    worker_model: str = "qwen3.5:2b-q4_K_M",
    ollama_base_url: str | None = None,
    require_docker: bool = True,
    require_local_worker: bool = True,
    require_harbor: bool = False,
    min_free_gb: float = 5.0,
    env: Mapping[str, str] | None = None,
    cmd_runner: CmdRunner = _default_cmd_runner,
    http_get: HttpJsonGetter = _default_http_json_getter,
    disk_usage: DiskUsageGetter = _default_disk_usage,
    which_fn: WhichGetter = shutil.which,
) -> dict[str, Any]:
    """Execute zero-LLM Host & Sandbox Preflight and return structured JSON-safe report."""
    env_map = env if env is not None else os.environ
    checks: list[PreflightCheck] = []

    checks.append(_check_docker(cmd_runner, required=require_docker))
    checks.append(_check_disk(repo_root, min_free_gb, disk_usage))
    checks.append(_check_provider_key(provider, repo_root / ".env", env_map))

    gpu_residency_pct: float | None = None
    if require_local_worker:
        ollama_url = (ollama_base_url or env_map.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).strip()
        worker_check, gpu_residency_pct = _check_local_worker(
            worker_model,
            ollama_url,
            http_get,
            cmd_runner,
            required=True,
        )
        checks.append(worker_check)

    checks.append(_check_harbor(which_fn, required=require_harbor))

    failed_required = [c.name for c in checks if c.required and not c.ok]
    return {
        "ready": len(failed_required) == 0,
        "provider": provider,
        "worker_model": worker_model if require_local_worker else None,
        "gpu_residency_pct": gpu_residency_pct,
        "failed_required": failed_required,
        "checks": [asdict(c) for c in checks],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mini Hivo Stage 0 Host & Sandbox Preflight Checker (zero LLM calls).")
    parser.add_argument(
        "--provider",
        choices=tuple(sorted(PROVIDER_ENV_VARS)),
        default="groq",
        help="Cloud orchestrator provider whose credential env var should be verified.",
    )
    parser.add_argument("--worker-model", default="qwen3.5:2b-q4_K_M", help="Local Ollama worker model tag.")
    parser.add_argument("--skip-docker", action="store_true", help="Do not require Docker daemon.")
    parser.add_argument("--skip-local-worker", action="store_true", help="Skip local Ollama worker check.")
    parser.add_argument("--require-harbor", action="store_true", help="Require Harbor CLI for Terminal-Bench 4.1.")
    parser.add_argument("--min-free-gb", type=float, default=5.0, help="Minimum free disk space in GB.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent.parent
    report = run_preflight(
        repo_root=repo_root,
        provider=args.provider,
        worker_model=args.worker_model,
        require_docker=not args.skip_docker,
        require_local_worker=not args.skip_local_worker,
        require_harbor=args.require_harbor,
        min_free_gb=args.min_free_gb,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Mini Hivo Benchmark Preflight — ready={report['ready']}")
        for chk in report["checks"]:
            tag = "PASS" if chk["ok"] else ("FAIL" if chk["required"] else "INFO")
            print(f"  [{tag:4s}] {chk['name']}: {chk['detail']}")
            if not chk["ok"] and chk.get("hint"):
                print(f"         hint: {chk['hint']}")

    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
