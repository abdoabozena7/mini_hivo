"""Mini Hivo Stage 0 benchmarking core: decontamination, auditing, KPIs, and preflight.

Zero external dependencies and zero imports from legacy ``mini.py``.
"""

from __future__ import annotations

from typing import Any

from .audit import (
    evaluate_baseline_oracle,
    evaluate_candidate_verdict,
    run_truth_check,
    scan_trace_for_cheats,
)
from .decontamination import (
    check_protected_paths_in_patch,
    docker_network_args,
    extract_patch_paths,
    strip_git_and_reinit,
    verify_workspace_decontaminated,
)
from .metrics import (
    FAILURE_BUCKET_KEYS,
    build_benchmark_results,
    classify_failure_bucket,
    compute_pass_hat_k,
    compute_percentile,
)

_PREFLIGHT_EXPORTS = frozenset({"PROVIDER_ENV_VARS", "PreflightCheck", "run_preflight"})


def __getattr__(name: str) -> Any:
    """Lazy-export preflight symbols so ``python -m hivo.benchmarks.preflight`` emits no runpy warning."""
    if name in _PREFLIGHT_EXPORTS:
        from . import preflight as _pf

        return getattr(_pf, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "FAILURE_BUCKET_KEYS",
    "PROVIDER_ENV_VARS",
    "PreflightCheck",
    "build_benchmark_results",
    "check_protected_paths_in_patch",
    "classify_failure_bucket",
    "compute_pass_hat_k",
    "compute_percentile",
    "docker_network_args",
    "evaluate_baseline_oracle",
    "evaluate_candidate_verdict",
    "extract_patch_paths",
    "run_preflight",
    "run_truth_check",
    "scan_trace_for_cheats",
    "strip_git_and_reinit",
    "verify_workspace_decontaminated",
]
