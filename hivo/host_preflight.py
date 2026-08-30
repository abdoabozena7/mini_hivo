"""Lightweight host qualification for local HIVO runs.

The preflight is deliberately separate from HIVO task execution.  It checks
the local Ollama endpoint, performs a tiny repeated inference using the
selected model, and persists enough state to identify a hard host restart on
the next startup.  It does not import or call the task controller.
"""

from __future__ import annotations

import csv
import ctypes
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .http_client import HttpTransportError, get_json, post_json


HOST_PREFLIGHT_MARKER = ".agent_host_preflight.json"
CANARY_PROMPT = "Reply with exactly: HIVO_PREFLIGHT_OK"
CANARY_EXPECTED_RESPONSE = "HIVO_PREFLIGHT_OK"
CANARY_CALLS = 3
CANARY_COOLDOWN_SECONDS = 2.0
CANARY_TIMEOUT_SECONDS = 30.0

# These are conservative named safety limits, not a hardware compatibility
# claim.  Unknown telemetry never trips them.
MIN_FREE_DISK_BYTES = 512 * 1024 * 1024
MIN_AVAILABLE_MEMORY_BYTES = 512 * 1024 * 1024
GPU_TEMPERATURE_WARNING_C = 85.0
GPU_TEMPERATURE_HARD_LIMIT_C = 95.0


class HostPreflightProbeError(RuntimeError):
    """A deterministic failure while probing Ollama before task execution."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)


def _compact(value, limit=320):
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _is_local_ollama_url(url):
    try:
        return urlparse(str(url)).hostname in {"127.0.0.1", "localhost", "::1"}
    except Exception:
        return False


def _memory_snapshot():
    """Return system memory bytes where the standard library can obtain them."""
    if os.name == "nt":
        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        try:
            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return {
                    "total_system_ram_bytes": int(status.ullTotalPhys),
                    "available_system_ram_bytes": int(status.ullAvailPhys),
                }
        except (AttributeError, OSError, TypeError):
            pass
        return {}

    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return {}
    values = {}
    try:
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, raw = line.partition(":")
            if key not in {"MemTotal", "MemAvailable", "MemFree"}:
                continue
            parts = raw.strip().split()
            if parts:
                values[key] = int(parts[0]) * 1024
    except (OSError, ValueError):
        return {}
    available = values.get("MemAvailable", values.get("MemFree"))
    result = {}
    if "MemTotal" in values:
        result["total_system_ram_bytes"] = values["MemTotal"]
    if available is not None:
        result["available_system_ram_bytes"] = available
    return result


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nvidia_gpu_snapshot():
    """Best-effort NVIDIA telemetry; absence is represented as UNKNOWN."""
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"status": "UNKNOWN", "source": "nvidia-smi", "reason": "unavailable"}
    query = ",".join((
        "name", "driver_version", "memory.total", "memory.used", "memory.free",
        "temperature.gpu", "utilization.gpu",
    ))
    try:
        completed = subprocess.run(
            [executable, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "UNKNOWN", "source": "nvidia-smi", "reason": _compact(exc)}
    if completed.returncode != 0 or not completed.stdout.strip():
        return {
            "status": "UNKNOWN", "source": "nvidia-smi",
            "reason": _compact(completed.stderr or f"exit code {completed.returncode}"),
        }
    try:
        row = next(csv.reader([completed.stdout.splitlines()[0]]))
        if len(row) < 7:
            raise ValueError("incomplete nvidia-smi row")
        values = [item.strip() for item in row]
        return {
            "status": "MEASURED", "source": "nvidia-smi", "name": values[0],
            "driver_version": values[1], "vram_total_mb": _number(values[2]),
            "vram_used_mb": _number(values[3]), "vram_free_mb": _number(values[4]),
            "temperature_c": _number(values[5]), "utilization_percent": _number(values[6]),
        }
    except (StopIteration, ValueError, IndexError):
        return {"status": "UNKNOWN", "source": "nvidia-smi", "reason": "unparseable telemetry"}


def sample_resources():
    """Capture resource state without making optional telemetry mandatory."""
    result = _memory_snapshot()
    result["gpu"] = _nvidia_gpu_snapshot()
    return result


def _safe_resource_snapshot(resource_sampler, phase, warnings):
    try:
        raw = resource_sampler() or {}
    except Exception as exc:  # telemetry must never crash qualification
        raw = {}
        warnings.add("resource_telemetry_error")
    if not isinstance(raw, dict):
        raw = {}
        warnings.add("resource_telemetry_unavailable")
    available = raw.get("available_system_ram_bytes", raw.get("available_memory_bytes"))
    total = raw.get("total_system_ram_bytes", raw.get("total_memory_bytes"))
    gpu = raw.get("gpu")
    if not isinstance(gpu, dict):
        gpu = {"status": "UNKNOWN", "reason": "unavailable"}
    status = str(gpu.get("status", "UNKNOWN")).upper()
    if status == "UNKNOWN":
        warnings.add("gpu_telemetry_unavailable")
    elif _number(gpu.get("temperature_c", gpu.get("temperature"))) is None:
        warnings.add("gpu_temperature_unavailable")
    if available is None:
        warnings.add("system_memory_telemetry_unavailable")
    return {
        "phase": phase,
        "sampled_at": _timestamp(),
        "total_system_ram_bytes": total,
        "available_system_ram_bytes": available,
        "gpu": gpu,
    }


def collect_host_inventory(model, workspace, before_snapshot):
    disk = shutil.disk_usage(workspace)
    return {
        "platform": platform.platform(),
        "os_version": f"{platform.system()} {platform.release()}".strip(),
        "python_version": platform.python_version(),
        "cpu_logical_count": os.cpu_count(),
        "total_system_ram_bytes": before_snapshot.get("total_system_ram_bytes"),
        "available_system_ram_bytes": before_snapshot.get("available_system_ram_bytes"),
        "selected_model": str(model),
        "ollama_availability": "UNKNOWN",
        "model_availability": "UNKNOWN",
        "free_workspace_disk_bytes": int(disk.free),
        "gpu": before_snapshot.get("gpu", {"status": "UNKNOWN"}),
    }


def _read_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _result(report, marker_path, persisted=True):
    return {
        "passed": report.get("status") == "PASS",
        "status": report.get("status", "FAIL"),
        "preflight_id": report.get("preflight_id"),
        "report": report,
        "marker_path": str(marker_path),
        "persisted": bool(persisted),
    }


def _finish_report(report, marker_path):
    report["finished_at"] = _timestamp()
    start_epoch = report.get("_start_epoch")
    if isinstance(start_epoch, (int, float)):
        report["duration_seconds"] = round(max(0.0, time.time() - start_epoch), 3)
    report.pop("_start_epoch", None)
    try:
        _atomic_write_json(marker_path, report)
        return _result(report, marker_path, persisted=True)
    except OSError as exc:
        report["status"] = "FAIL"
        report["terminal_state"] = "HOST_PREFLIGHT_FAILED"
        report["failure_stage"] = "completion"
        report["failure_reason"] = "WORKSPACE_UNUSABLE"
        report["persistence_error"] = _compact(exc)
        return _result(report, marker_path, persisted=False)


def _base_report(model, preflight_id, started_at, inventory, snapshots, warnings):
    return {
        "status": "FAIL",
        "terminal_state": "HOST_PREFLIGHT_FAILED",
        "preflight_id": preflight_id,
        "started_at": started_at,
        "model": str(model),
        "pid": os.getpid(),
        "canary_calls_requested": CANARY_CALLS,
        "canary_calls_completed": 0,
        "canary_prompt": CANARY_PROMPT,
        "resource_snapshots": snapshots,
        "inventory": inventory,
        "warnings": sorted(warnings),
        "provider_evidence": [],
    }


def _persist_ordinary_failure(report, marker_path, *, stage, reason, summary=None, previous=None):
    report["failure_stage"] = stage
    report["failure_reason"] = reason
    if summary:
        report["failure_summary"] = _compact(summary)
    if previous is not None:
        report["previous_preflight"] = {
            "preflight_id": previous.get("preflight_id"),
            "started_at": previous.get("started_at"),
            "model": previous.get("model"),
            "pid": previous.get("pid"),
        }
    report["warnings"] = sorted(set(report.get("warnings", [])))
    return _finish_report(report, marker_path)


def failed_host_preflight_result(workspace, model, *, reason, stage="startup", summary=None):
    """Build a structured setup failure when the workspace cannot be probed.

    An unusable or missing workspace cannot safely receive the persistent
    marker.  The caller still gets the same structured report, explicitly
    marked as not persisted, without creating the requested workspace as a
    side effect.
    """
    workspace = Path(workspace).expanduser().resolve()
    report = _base_report(str(model), uuid.uuid4().hex, _timestamp(), {}, [], set())
    report["_start_epoch"] = time.time()
    if workspace.exists() and workspace.is_dir() and os.access(str(workspace), os.W_OK):
        return _persist_ordinary_failure(
            report, workspace / HOST_PREFLIGHT_MARKER,
            stage=stage, reason=reason, summary=summary,
        )
    report["failure_stage"] = stage
    report["failure_reason"] = reason
    if summary:
        report["failure_summary"] = _compact(summary)
    report["finished_at"] = _timestamp()
    report["duration_seconds"] = 0.0
    report.pop("_start_epoch", None)
    return _result(report, workspace / HOST_PREFLIGHT_MARKER, persisted=False)


def _load_local_models(base_url):
    if not _is_local_ollama_url(base_url):
        raise HostPreflightProbeError("OLLAMA_UNAVAILABLE", "Ollama URL is not local")
    try:
        response = get_json(str(base_url).rstrip("/") + "/api/tags", timeout=5)
    except HttpTransportError as exc:
        raise HostPreflightProbeError("OLLAMA_UNAVAILABLE", str(exc)) from exc
    except Exception as exc:
        raise HostPreflightProbeError("OLLAMA_UNAVAILABLE", str(exc)) from exc
    if response.status_code != 200:
        raise HostPreflightProbeError("OLLAMA_UNAVAILABLE", f"/api/tags returned {response.status_code}")
    try:
        body = response.json()
    except (ValueError, TypeError) as exc:
        raise HostPreflightProbeError("OLLAMA_UNAVAILABLE", f"invalid /api/tags response: {exc}") from exc
    if not isinstance(body, dict) or not isinstance(body.get("models", []), list):
        raise HostPreflightProbeError("OLLAMA_UNAVAILABLE", "invalid /api/tags model list")
    return body.get("models", [])


def _catalog_names(catalog):
    if isinstance(catalog, dict):
        catalog = catalog.get("models", [])
    names = []
    for item in catalog or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("model")
            if name:
                names.append(str(name))
    return names


def _default_canary_call(model, prompt, timeout, base_url):
    payload = {
        "model": str(model),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0, "seed": 0, "num_ctx": 512, "num_predict": 32},
    }
    response = post_json(str(base_url).rstrip("/") + "/api/chat", timeout=timeout, payload=payload)
    try:
        body = response.json()
    except (ValueError, TypeError):
        body = None
    return {"status_code": response.status_code, "text": response.text, "body": body}


def _load_failure_text(response):
    if not isinstance(response, dict):
        return "invalid canary response"
    body = response.get("body")
    if isinstance(body, dict) and body.get("error"):
        return _compact(body.get("error"), 500)
    return _compact(response.get("text", "provider returned no usable response"), 500)


def _looks_like_model_load_failure(text):
    lower = str(text).casefold()
    return any(marker in lower for marker in (
        "model not found", "model runner", "failed to load", "loading model",
        "unable to load", "cuda error", "out of memory", "runner has unexpectedly stopped",
    ))


def _validate_canary_response(response):
    if not isinstance(response, dict):
        return "CANARY_PROVIDER_FAILURE", "canary callback returned no response"
    status_code = response.get("status_code", 200)
    try:
        status_code = int(status_code)
    except (TypeError, ValueError):
        status_code = 0
    if status_code != 200:
        summary = _load_failure_text(response)
        code = "MODEL_LOAD_FAILED" if _looks_like_model_load_failure(summary) else "CANARY_PROVIDER_FAILURE"
        return code, f"HTTP {status_code}: {summary}"
    body = response.get("body")
    if isinstance(body, dict) and body.get("error"):
        summary = _compact(body.get("error"), 500)
        code = "MODEL_LOAD_FAILED" if _looks_like_model_load_failure(summary) else "CANARY_PROVIDER_FAILURE"
        return code, summary
    content = None
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, dict):
            content = message.get("content")
        content = content if content is not None else body.get("content", body.get("response"))
    if content is None:
        content = response.get("content")
    if str(content or "").strip() != CANARY_EXPECTED_RESPONSE:
        return "CANARY_PROVIDER_FAILURE", "unexpected canary response"
    return None, None


def _resource_blocker(snapshot):
    available = _number(snapshot.get("available_system_ram_bytes"))
    if available is not None and available < MIN_AVAILABLE_MEMORY_BYTES:
        return "CRITICAL_MEMORY_HEADROOM", f"available system memory is {int(available)} bytes"
    gpu = snapshot.get("gpu") if isinstance(snapshot.get("gpu"), dict) else {}
    temperature = _number(gpu.get("temperature_c", gpu.get("temperature")))
    if temperature is not None and temperature >= GPU_TEMPERATURE_HARD_LIMIT_C:
        return "CRITICAL_TEMPERATURE", f"GPU temperature is {temperature:g} C"
    return None


def _add_temperature_warning(snapshot, warnings):
    gpu = snapshot.get("gpu") if isinstance(snapshot.get("gpu"), dict) else {}
    temperature = _number(gpu.get("temperature_c", gpu.get("temperature")))
    if temperature is not None and temperature >= GPU_TEMPERATURE_WARNING_C:
        warnings.add("gpu_temperature_elevated")


def run_host_preflight(
    workspace, model, base_url,
    *, model_catalog_loader=None, canary_call=None, resource_sampler=None,
    sleep=None, preflight_id=None,
):
    """Run and persist one bounded host qualification.

    The injectable loaders are intentionally small seams for deterministic
    tests.  Production defaults use the existing standard-library Ollama
    transport and local resource probes.
    """
    workspace = Path(workspace).expanduser().resolve()
    marker_path = workspace / HOST_PREFLIGHT_MARKER
    model = str(model)
    preflight_id = preflight_id or uuid.uuid4().hex
    started_at = _timestamp()
    start_epoch = time.time()
    warnings = set()
    resource_sampler = resource_sampler or sample_resources
    model_catalog_loader = model_catalog_loader or _load_local_models
    canary_call = canary_call or _default_canary_call
    sleep = time.sleep if sleep is None else sleep

    if not workspace.exists() or not workspace.is_dir() or not os.access(str(workspace), os.W_OK):
        report = _base_report(model, preflight_id, started_at, {}, [], warnings)
        report["failure_stage"] = "workspace"
        report["failure_reason"] = "WORKSPACE_UNUSABLE"
        report["failure_summary"] = "workspace is missing or not writable"
        report["finished_at"] = _timestamp()
        report["duration_seconds"] = 0.0
        return _result(report, marker_path, persisted=False)

    try:
        before = _safe_resource_snapshot(resource_sampler, "before_canary", warnings)
        inventory = collect_host_inventory(model, workspace, before)
    except OSError as exc:
        report = _base_report(model, preflight_id, started_at, {}, [], warnings)
        report["_start_epoch"] = start_epoch
        return _persist_ordinary_failure(
            report, marker_path, stage="workspace", reason="WORKSPACE_UNUSABLE", summary=exc,
        )
    snapshots = [before]
    report = _base_report(model, preflight_id, started_at, inventory, snapshots, warnings)
    report["_start_epoch"] = start_epoch

    prior = _read_json(marker_path)
    if isinstance(prior, dict) and str(prior.get("status", "")).upper() == "RUNNING":
        return _persist_ordinary_failure(
            report, marker_path, stage="startup", reason="PREVIOUS_HOST_PREFLIGHT_INTERRUPTED",
            summary="a prior host preflight was left RUNNING", previous=prior,
        )

    blocker = _resource_blocker(before)
    _add_temperature_warning(before, warnings)
    report["warnings"] = sorted(warnings)
    if blocker:
        return _persist_ordinary_failure(
            report, marker_path, stage="static_resources", reason=blocker[0], summary=blocker[1],
        )
    if inventory["free_workspace_disk_bytes"] < MIN_FREE_DISK_BYTES:
        return _persist_ordinary_failure(
            report, marker_path, stage="static_resources", reason="CRITICAL_FREE_DISK",
            summary=f"free workspace disk is {inventory['free_workspace_disk_bytes']} bytes",
        )

    try:
        catalog = model_catalog_loader(str(base_url).rstrip("/"))
    except HostPreflightProbeError as exc:
        inventory["ollama_availability"] = "FAIL"
        report["inventory"] = inventory
        return _persist_ordinary_failure(
            report, marker_path, stage="ollama", reason=exc.code, summary=exc.message,
        )
    except Exception as exc:
        inventory["ollama_availability"] = "FAIL"
        report["inventory"] = inventory
        return _persist_ordinary_failure(
            report, marker_path, stage="ollama", reason="OLLAMA_UNAVAILABLE", summary=exc,
        )

    inventory["ollama_availability"] = "PASS"
    names = _catalog_names(catalog)
    if model not in names:
        inventory["model_availability"] = "FAIL"
        report["inventory"] = inventory
        return _persist_ordinary_failure(
            report, marker_path, stage="model", reason="MODEL_UNAVAILABLE",
            summary=f"selected model {model!r} was not reported by Ollama",
        )
    inventory["model_availability"] = "PASS"
    report["inventory"] = inventory

    # This is the only RUNNING marker.  It is written before the first model
    # invocation so a hard reboot leaves an observable interrupted state.
    running_report = dict(report)
    running_report["status"] = "RUNNING"
    running_report.pop("terminal_state", None)
    running_report["warnings"] = sorted(warnings)
    try:
        _atomic_write_json(marker_path, running_report)
    except OSError as exc:
        report["_start_epoch"] = start_epoch
        return _persist_ordinary_failure(
            report, marker_path, stage="workspace", reason="WORKSPACE_UNUSABLE", summary=exc,
        )

    completed = 0
    for index in range(CANARY_CALLS):
        call_number = index + 1
        try:
            response = canary_call(model, CANARY_PROMPT, CANARY_TIMEOUT_SECONDS, str(base_url).rstrip("/"))
            failure_code, failure_summary = _validate_canary_response(response)
        except (TimeoutError, subprocess.TimeoutExpired) as exc:
            response = None
            failure_code, failure_summary = "CANARY_TIMEOUT", _compact(exc)
        except Exception as exc:
            response = None
            text = _compact(exc)
            failure_code = "CANARY_TIMEOUT" if "timeout" in text.casefold() else "CANARY_PROVIDER_FAILURE"
            failure_summary = text

        if failure_code:
            snapshots.append(_safe_resource_snapshot(resource_sampler, f"after_call_{call_number}", warnings))
            report["resource_snapshots"] = snapshots
            report["canary_calls_completed"] = completed
            report["provider_evidence"].append({
                "call": call_number, "category": failure_code,
                "summary": _compact(failure_summary),
            })
            report["inventory"] = inventory
            report["warnings"] = sorted(warnings)
            return _persist_ordinary_failure(
                report, marker_path, stage="canary", reason=failure_code, summary=failure_summary,
            )

        completed = call_number
        after = _safe_resource_snapshot(resource_sampler, f"after_call_{call_number}", warnings)
        snapshots.append(after)
        resource_failure = _resource_blocker(after)
        _add_temperature_warning(after, warnings)
        if resource_failure:
            report["resource_snapshots"] = snapshots
            report["canary_calls_completed"] = completed
            report["inventory"] = inventory
            report["warnings"] = sorted(warnings)
            return _persist_ordinary_failure(
                report, marker_path, stage="resource_monitoring",
                reason=resource_failure[0], summary=resource_failure[1],
            )
        if call_number < CANARY_CALLS:
            sleep(CANARY_COOLDOWN_SECONDS)

    # Keep a final post-cooldown snapshot, including the final fixed cooldown
    # that separates preflight completion from HIVO startup.
    sleep(CANARY_COOLDOWN_SECONDS)
    snapshots.append(_safe_resource_snapshot(resource_sampler, "after_final_cooldown", warnings))
    final_failure = _resource_blocker(snapshots[-1])
    _add_temperature_warning(snapshots[-1], warnings)
    report["status"] = "PASS" if final_failure is None else "FAIL"
    report["terminal_state"] = "HOST_PREFLIGHT_PASSED" if final_failure is None else "HOST_PREFLIGHT_FAILED"
    report["canary_calls_completed"] = completed
    report["resource_snapshots"] = snapshots
    report["inventory"] = inventory
    report["warnings"] = sorted(warnings)
    if final_failure:
        report["failure_stage"] = "resource_monitoring"
        report["failure_reason"] = final_failure[0]
        report["failure_summary"] = final_failure[1]
    return _finish_report(report, marker_path)


def _format_bytes(value):
    if value is None:
        return "UNKNOWN"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while abs(value) >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.1f} {units[index]}"


def format_host_preflight_report(result):
    """Render a compact user-facing report without exposing internal details."""
    report = result.get("report", result) if isinstance(result, dict) else {}
    inventory = report.get("inventory") or {}
    before = (report.get("resource_snapshots") or [{}])[0]
    gpu = inventory.get("gpu") or before.get("gpu") or {"status": "UNKNOWN"}
    status = str(report.get("status", "FAIL")).upper()
    lines = [f"HIVO HOST PREFLIGHT: {status}", "", f"Selected model: {report.get('model', 'UNKNOWN')}"]
    if status == "FAIL":
        lines.extend([
            f"Failure: {report.get('failure_reason', 'HOST_PREFLIGHT_FAILED')}",
            f"Failure stage: {report.get('failure_stage', 'UNKNOWN')}",
        ])
    vram_free = gpu.get("vram_free_mb")
    vram_text = "UNKNOWN" if vram_free is None else f"{vram_free} MB"
    temperature = gpu.get("temperature_c", "UNKNOWN")
    temperature_text = "UNKNOWN" if temperature is None else f"{temperature} C"
    lines.extend([
        f"Completed canary calls: {report.get('canary_calls_completed', 0)}/{report.get('canary_calls_requested', CANARY_CALLS)}",
        f"System RAM: total {_format_bytes(inventory.get('total_system_ram_bytes'))}; "
        f"available before {_format_bytes(before.get('available_system_ram_bytes'))}",
        f"GPU: {gpu.get('name', 'UNKNOWN')} | VRAM free {vram_text} | temperature {temperature_text}",
        f"Warnings: {', '.join(report.get('warnings') or []) or 'none'}",
        "Recommended action: inspect host/model stability before retrying." if status == "FAIL"
        else "Starting HIVO...",
    ])
    return "\n".join(lines)


__all__ = [
    "CANARY_CALLS", "CANARY_COOLDOWN_SECONDS", "CANARY_EXPECTED_RESPONSE", "CANARY_PROMPT",
    "CANARY_TIMEOUT_SECONDS", "GPU_TEMPERATURE_HARD_LIMIT_C", "GPU_TEMPERATURE_WARNING_C",
    "HOST_PREFLIGHT_MARKER", "MIN_AVAILABLE_MEMORY_BYTES", "MIN_FREE_DISK_BYTES",
    "HostPreflightProbeError", "collect_host_inventory", "failed_host_preflight_result",
    "format_host_preflight_report", "run_host_preflight", "sample_resources",
]
